import React, { useState, useEffect } from 'react'
import { Card, Row, Col, Tag, Spin, message, Table, Typography } from 'antd'
import { getDiagnosticInfo, getDetailedDiagnostics } from '../services/api'
import TopologyMap from '../components/TopologyMap'

const { Title, Text } = Typography

/**
 * 服务诊断页面组件
 * 
 * 显示所有服务的诊断信息，包括：
 * - 服务注册状态
 * - 健康状态
 * - 元数据信息
 * - 最后心跳时间
 * - 统计信息
 */
const ServiceStatus = () => {
  const [diagnosticData, setDiagnosticData] = useState(null)
  const [detailedDiagnostics, setDetailedDiagnostics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdateTime, setLastUpdateTime] = useState(null)
  const [selectedService, setSelectedService] = useState('engine') // 默认选中第一个服务

  useEffect(() => {
    // 立即加载一次
    loadDiagnosticInfo()
    loadDetailedDiagnostics()

    // 设置定时刷新（每1秒刷新一次）
    const interval = setInterval(() => {
      loadDiagnosticInfo()
      loadDetailedDiagnostics()
    }, 1000)

    return () => {
      clearInterval(interval)
    }
  }, [])

  const loadDiagnosticInfo = async () => {
    try {
      const data = await getDiagnosticInfo()
      if (data.status === 'ok') {
        setDiagnosticData(data)
        setLastUpdateTime(new Date())
      } else {
        message.error('获取诊断信息失败')
      }
    } catch (error) {
      console.error('加载诊断信息失败:', error)
      message.error('加载诊断信息失败')
    } finally {
      setLoading(false)
    }
  }

  const loadDetailedDiagnostics = async () => {
    try {
      const data = await getDetailedDiagnostics()
      if (data.status === 'ok') {
        setDetailedDiagnostics(data.diagnostics || {})
      }
    } catch (error) {
      console.error('加载详细诊断信息失败:', error)
      // 不显示错误消息，因为详细诊断信息是可选的
    }
  }

  /**
   * 获取健康状态标签颜色
   */
  const getHealthColor = (health) => {
    switch (health) {
      case 'healthy':
        return 'success'
      case 'waiting':
        return 'warning'
      case 'unhealthy':
      case 'error':
        return 'error'
      default:
        return 'default'
    }
  }

  /**
   * 格式化时间
   */
  const formatTime = (timestamp) => {
    if (!timestamp) return '未知'
    const date = new Date(timestamp * 1000) // Redis 返回的是秒级时间戳
    return date.toLocaleString('zh-CN')
  }

  /**
   * 格式化服务名称（显示名称）
   */
  const getServiceDisplayName = (serviceName) => {
    const nameMap = {
      'storage_service': 'StorageService 历史数据服务',
      'opcua_server': 'OPCUA Server OPCUA服务',
    }
    if (nameMap[serviceName]) return nameMap[serviceName]

    if (serviceName.startsWith('engine')) {
      const parts = serviceName.split('.')
      const engineId = parts.length > 1 ? parts[1] : 'default'
      return `Engine 引擎 [${engineId}]`
    }

    return serviceName
  }

  /**
   * 获取运行状态字段名
   */
  const getRunningFieldName = (serviceName) => {
    return `${serviceName}_running`
  }

  /**
   * 获取服务列表
   */
  const getServiceList = () => {
    const staticServices = ['storage_service', 'opcua_server']
    if (!diagnosticData || !diagnosticData.services_status) return ['engine', ...staticServices]

    // 从已注册服务中提取引擎
    const engines = Object.keys(diagnosticData.services_status)
      .filter(name => name.startsWith('engine'))
      .sort()

    // 如果没有发现具体引擎，保留默认占位
    if (engines.length === 0) return ['engine', ...staticServices]

    return [...engines, ...staticServices]
  }

  /**
   * 渲染服务卡片（左侧）
   */
  const renderServiceCard = (serviceName) => {
    if (!diagnosticData) return null

    const servicesStatus = diagnosticData.services_status || {}
    const serviceStatus = servicesStatus[serviceName] || {}
    const runningFieldName = getRunningFieldName(serviceName)
    const isRunning = diagnosticData[runningFieldName] || false
    const isSelected = selectedService === serviceName

    return (
      <Card
        key={serviceName}
        size="small"
        style={{
          marginBottom: '12px',
          cursor: 'pointer',
          border: isSelected ? '2px solid #1890ff' : '1px solid #d9d9d9',
          backgroundColor: isSelected ? '#e6f7ff' : '#fff',
        }}
        onClick={() => setSelectedService(serviceName)}
        hoverable
      >
        <div>
          <Title level={5} style={{ margin: '0 0 8px 0' }}>
            {getServiceDisplayName(serviceName)}
          </Title>
          <div style={{ marginBottom: '4px' }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>注册状态: </Text>
            <Tag color={serviceStatus.registered ? 'success' : 'default'} size="small">
              {serviceStatus.registered ? '已注册' : '未注册'}
            </Tag>
          </div>
          <div style={{ marginBottom: '4px' }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>运行状态: </Text>
            <Tag color={isRunning ? 'success' : 'default'} size="small">
              {isRunning ? '运行中' : '已停止'}
            </Tag>
          </div>
          {serviceStatus.last_heartbeat && (
            <div>
              <Text type="secondary" style={{ fontSize: '12px' }}>最后心跳: </Text>
              <Text style={{ fontSize: '12px' }}>{formatTime(serviceStatus.last_heartbeat)}</Text>
            </div>
          )}
        </div>
      </Card>
    )
  }

  /**
   * 渲染诊断信息表格（右侧）
   */
  const renderDiagnosticTable = () => {
    if (!detailedDiagnostics || !detailedDiagnostics[selectedService]) {
      return (
        <Card>
          <div style={{ textAlign: 'center', padding: '50px' }}>
            <Text type="secondary">暂无诊断信息</Text>
          </div>
        </Card>
      )
    }

    const diagnosticInfo = detailedDiagnostics[selectedService]
    const items = diagnosticInfo.items || []

    // 准备表格数据
    const tableData = items.map((item, index) => ({
      key: index,
      name: item.description || item.name,
      value: item.value !== null && item.value !== undefined ? String(item.value) : 'N/A',
      unit: item.unit || '',
    }))

    // 表格列定义
    const columns = [
      {
        title: '诊断项',
        dataIndex: 'name',
        key: 'name',
        width: '50%',
      },
      {
        title: '值',
        dataIndex: 'value',
        key: 'value',
        width: '50%',
        render: (text, record) => (
          <span>
            {text} {record.unit && <Text type="secondary">{record.unit}</Text>}
          </span>
        ),
      },
    ]

    return (
      <Card
        title={getServiceDisplayName(selectedService) + ' - 诊断信息'}
        extra={
          diagnosticInfo.timestamp && (
            <Text type="secondary" style={{ fontSize: '12px' }}>
              更新时间: {formatTime(diagnosticInfo.timestamp)}
            </Text>
          )
        }
      >
        <Table
          columns={columns}
          dataSource={tableData}
          pagination={false}
          size="small"
          bordered
        />
      </Card>
    )
  }

  if (loading && !diagnosticData) {
    return (
      <div style={{ textAlign: 'center', padding: '50px' }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div style={{ padding: '24px', height: 'calc(100vh - 64px)' }}>
      <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={2} style={{ margin: 0 }}>服务诊断</Title>
        {lastUpdateTime && (
          <Text type="secondary">
            最后刷新: {lastUpdateTime.toLocaleString('zh-CN')}
          </Text>
        )}
      </div>

      <Row gutter={16} style={{ marginBottom: '16px' }}>
        <Col span={24}>
          <Card size="small">
            <TopologyMap
              diagnosticData={diagnosticData}
              detailedDiagnostics={detailedDiagnostics}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ height: 'calc(100% - 460px)' }}>
        {/* 左侧：服务卡片列表 */}
        <Col span={7} style={{ height: '100%', overflowY: 'auto' }}>
          <div>
            {getServiceList().map(serviceName => renderServiceCard(serviceName))}
          </div>
        </Col>

        {/* 右侧：诊断信息表格 */}
        <Col span={17} style={{ height: '100%', overflowY: 'auto' }}>
          {renderDiagnosticTable()}
        </Col>
      </Row>
    </div>
  )
}

export default ServiceStatus

