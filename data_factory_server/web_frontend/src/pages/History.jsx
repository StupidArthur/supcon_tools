import React, { useState, useEffect, useRef } from 'react'
import { Row, Col, Tree, Card, Typography, Button, message, Spin, DatePicker, InputNumber, Space } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactECharts from 'echarts-for-react'
import { getRealtimeConfigFromRedis, queryHistoryData } from '../services/api'

const { Title, Text } = Typography

/**
 * 历史数据页面
 * 
 * 左侧：三级树（namespace -> 实例/变量 -> 位号）
 * 右侧：时间控件、查询按钮和曲线图
 */
const History = () => {
  const [treeData, setTreeData] = useState([])
  const [selectedNode, setSelectedNode] = useState(null)
  const [loading, setLoading] = useState(false)
  const [queryLoading, setQueryLoading] = useState(false)
  
  // 时间控件状态
  const [startTime, setStartTime] = useState(null)
  const [endTime, setEndTime] = useState(dayjs())
  const [timeLength, setTimeLength] = useState(1200) // 默认1200秒
  
  // 图表数据
  const [chartData, setChartData] = useState(null)
  
  /**
   * 将后端返回的树结构转换为Ant Design Tree组件需要的格式
   */
  const convertToTreeData = (tree) => {
    const result = []
    
    for (const [namespace, namespaceData] of Object.entries(tree)) {
      const namespaceNode = {
        title: namespace,
        key: `namespace:${namespace}`,
        children: [],
      }
      
      // 添加实例节点
      const instances = namespaceData.instances || {}
      for (const [instanceName, instanceData] of Object.entries(instances)) {
        const instanceNode = {
          title: instanceName,
          key: `instance:${instanceData.full_name}`,
          children: [],
        }
        
        // 添加实例的属性（位号）节点
        const attributes = instanceData.attributes || []
        for (const attr of attributes) {
          instanceNode.children.push({
            title: attr.name,
            key: `attribute:${attr.full_name}`,
            isLeaf: true,
          })
        }
        
        namespaceNode.children.push(instanceNode)
      }
      
      // 添加变量节点
      const variables = namespaceData.variables || {}
      for (const [varName, varData] of Object.entries(variables)) {
        namespaceNode.children.push({
          title: varName,
          key: `variable:${varData.full_name}`,
          isLeaf: true,
        })
      }
      
      result.push(namespaceNode)
    }
    
    return result
  }

  /**
   * 从Redis获取组态数据
   */
  const fetchConfigData = async () => {
    setLoading(true)
    try {
      const response = await getRealtimeConfigFromRedis()
      if (response.status === 'ok' && response.tree) {
        const tree = convertToTreeData(response.tree)
        setTreeData(tree)
        message.success('组态数据已刷新')
      } else {
        setTreeData([])
        message.warning('Redis中暂无组态数据')
      }
    } catch (error) {
      console.error('获取组态数据失败:', error)
      message.error(`获取组态数据失败: ${error.response?.data?.detail || error.message}`)
      setTreeData([])
    } finally {
      setLoading(false)
    }
  }

  /**
   * 执行历史数据查询
   */
  const handleQuery = async () => {
    if (!selectedNode) {
      message.warning('请先选择一个位号节点')
      return
    }
    
    // 检查是否是叶子节点
    if (!selectedNode.isLeaf) {
      message.warning('请选择具体的位号节点（叶子节点）')
      return
    }
    
    if (!endTime) {
      message.warning('请设置终止时间')
      return
    }
    
    if (!timeLength || timeLength <= 0) {
      message.warning('请设置有效的时间长度')
      return
    }
    
    await handleQueryWithParams(selectedNode.fullName, endTime, timeLength)
  }

  /**
   * 树节点选中事件
   */
  const handleSelect = (selectedKeys, info) => {
    if (selectedKeys.length === 0) {
      setSelectedNode(null)
      return
    }
    
    const key = selectedKeys[0]
    const node = info.node
    
    // 从key中提取完整名字
    let fullName = ''
    let isLeaf = false
    if (key.startsWith('namespace:')) {
      fullName = key.replace('namespace:', '')
      isLeaf = false
    } else if (key.startsWith('instance:')) {
      fullName = key.replace('instance:', '')
      isLeaf = false
    } else if (key.startsWith('attribute:')) {
      fullName = key.replace('attribute:', '')
      isLeaf = true
    } else if (key.startsWith('variable:')) {
      fullName = key.replace('variable:', '')
      isLeaf = true
    }
    
    const newNode = {
      key,
      title: node.title,
      fullName,
      isLeaf,
    }
    
    setSelectedNode(newNode)
    
    // 如果是叶子节点，自动执行查询
    if (isLeaf) {
      // 设置默认终止时间为当前时间
      const currentEndTime = dayjs()
      setEndTime(currentEndTime)
      // 设置默认时间长度为1200秒
      setTimeLength(1200)
      // 延迟执行查询，确保状态更新完成
      setTimeout(() => {
        // 使用最新的状态值执行查询
        handleQueryWithParams(newNode.fullName, currentEndTime, 1200)
      }, 100)
    }
  }

  /**
   * 使用指定参数执行查询（用于自动查询）
   */
  const handleQueryWithParams = async (paramName, endTimeValue, timeLengthValue) => {
    if (!paramName || !endTimeValue || !timeLengthValue || timeLengthValue <= 0) {
      return
    }
    
    setQueryLoading(true)
    try {
      const response = await queryHistoryData({
        param_name: paramName,
        end_time: endTimeValue.toISOString(),
        time_length: timeLengthValue,
        sample_points: 1200, // 固定1200点
      })
      
      if (response.status === 'ok' && response.data) {
        // 计算起始时间
        const calculatedStartTime = dayjs(response.start_time)
        setStartTime(calculatedStartTime)
        
        // 处理图表数据
        const data = response.data
        // 按时间排序（升序）
        data.sort((a, b) => {
          const timeA = dayjs(a.timestamp).valueOf()
          const timeB = dayjs(b.timestamp).valueOf()
          return timeA - timeB
        })
        
        // 提取时间和值
        const times = data.map(item => dayjs(item.timestamp).format('YYYY-MM-DD HH:mm:ss'))
        const values = data.map(item => parseFloat(item.param_value) || 0)
        
        setChartData({
          times,
          values,
          paramName: response.param_name,
        })
        
        message.success(`查询成功，共 ${response.sample_points} 个数据点`)
      } else {
        message.warning('查询结果为空')
        setChartData(null)
      }
    } catch (error) {
      console.error('查询历史数据失败:', error)
      message.error(`查询失败: ${error.response?.data?.detail || error.message}`)
      setChartData(null)
    } finally {
      setQueryLoading(false)
    }
  }

  // 组件挂载时自动加载数据
  useEffect(() => {
    fetchConfigData()
    // 设置默认终止时间为当前时间
    setEndTime(dayjs())
  }, [])

  // 图表配置
  const getChartOption = () => {
    if (!chartData) {
      return {
        title: {
          text: '暂无数据',
          left: 'center',
          top: 'middle',
          textStyle: {
            color: '#999',
            fontSize: 16,
          },
        },
      }
    }
    
    return {
      title: {
        text: chartData.paramName,
        left: 'center',
        textStyle: {
          fontSize: 16,
          fontWeight: 'bold',
        },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
        formatter: (params) => {
          const param = params[0]
          return `
            <div>
              <div>时间: ${param.axisValue}</div>
              <div>值: ${param.value}</div>
            </div>
          `
        },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: chartData.times,
        axisLabel: {
          rotate: 45,
          interval: Math.floor(chartData.times.length / 10), // 显示约10个标签
        },
      },
      yAxis: {
        type: 'value',
      },
      series: [
        {
          name: chartData.paramName,
          type: 'line',
          smooth: true,
          data: chartData.values,
          itemStyle: {
            color: '#1890ff',
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(24, 144, 255, 0.3)' },
                { offset: 1, color: 'rgba(24, 144, 255, 0.1)' },
              ],
            },
          },
        },
      ],
    }
  }

  return (
    <div>
      <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={2} style={{ margin: 0 }}>历史数据</Title>
        <Button
          type="primary"
          icon={<ReloadOutlined />}
          onClick={fetchConfigData}
          loading={loading}
        >
          刷新组态
        </Button>
      </div>
      
      <Row gutter={16}>
        {/* 左侧：三级树（占25%） */}
        <Col span={6}>
          <Card title="组态树" style={{ height: 'calc(100vh - 200px)', overflow: 'auto' }}>
            <Spin spinning={loading}>
              {treeData.length > 0 ? (
                <Tree
                  treeData={treeData}
                  onSelect={handleSelect}
                  selectedKeys={selectedNode ? [selectedNode.key] : []}
                  showLine
                />
              ) : (
                <div style={{ padding: '24px', textAlign: 'center', color: '#999' }}>
                  暂无组态数据，请先加载配置
                </div>
              )}
            </Spin>
          </Card>
        </Col>

        {/* 右侧：时间控件、查询按钮和曲线图（占70%） */}
        <Col span={18}>
          <Card 
            title="历史数据" 
            style={{ height: 'calc(100vh - 200px)', display: 'flex', flexDirection: 'column' }}
            bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, padding: '16px' }}
          >
            <div style={{ flexShrink: 0, marginBottom: '16px' }}>
              {selectedNode ? (
                <div style={{ marginBottom: '16px' }}>
                  <Text strong>选中位号：</Text>
                  <Text code style={{ fontSize: '14px', color: '#1890ff' }}>
                    {selectedNode.fullName}
                  </Text>
                </div>
              ) : (
                <Text type="secondary">请从左侧树中选择一个位号节点</Text>
              )}
            </div>
            
            <div style={{ flexShrink: 0, marginBottom: '16px' }}>
              <Space direction="vertical" style={{ width: '100%' }} size="middle">
                <Space>
                  <Text strong>起始时间：</Text>
                  <DatePicker
                    showTime
                    format="YYYY-MM-DD HH:mm:ss"
                    value={startTime}
                    disabled
                    style={{ width: 200 }}
                  />
                  <Text type="secondary" style={{ fontSize: '12px' }}>（自动计算，不可编辑）</Text>
                </Space>
                
                <Space>
                  <Text strong>终止时间：</Text>
                  <DatePicker
                    showTime
                    format="YYYY-MM-DD HH:mm:ss"
                    value={endTime}
                    onChange={(value) => setEndTime(value)}
                    style={{ width: 200 }}
                  />
                </Space>
                
                <Space>
                  <Text strong>时间长度：</Text>
                  <InputNumber
                    min={1}
                    value={timeLength}
                    onChange={(value) => setTimeLength(value)}
                    addonAfter="秒"
                    style={{ width: 150 }}
                  />
                </Space>
                
                <Space>
                  <Button
                    type="primary"
                    icon={<SearchOutlined />}
                    onClick={handleQuery}
                    loading={queryLoading}
                    disabled={!selectedNode || !selectedNode.isLeaf}
                  >
                    查询
                  </Button>
                </Space>
              </Space>
            </div>
            
            <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <ReactECharts
                option={getChartOption()}
                style={{ height: '100%', width: '100%', minHeight: 0 }}
                opts={{ renderer: 'canvas' }}
                notMerge={true}
                showLoading={false}
                loadingOption={{ show: false }}
              />
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default History
