import React, { useState, useEffect, useRef } from 'react'
import { 
  Row, 
  Col, 
  Tree, 
  Card, 
  Typography, 
  Button, 
  message, 
  Spin, 
  Table, 
  Input,
  Space,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { 
  getRealtimeConfigFromRedis, 
  getRealtimeSnapshot,
  patchInstanceParams,
  patchVariable,
} from '../services/api'

const { Title, Text } = Typography

/**
 * 实时数据页面
 * 
 * 左侧：两级树（namespace -> 实例/程序/Variable）
 * 右侧：表格显示参数信息，支持写值
 */
const RealtimeRun = () => {
  const [treeData, setTreeData] = useState([])
  const [selectedNode, setSelectedNode] = useState(null)
  const [loading, setLoading] = useState(false)
  const [snapshotData, setSnapshotData] = useState(null)
  const [writeValues, setWriteValues] = useState({}) // 存储写值输入框的值
  const [writing, setWriting] = useState({}) // 存储正在写入的状态
  
  // 用于定时刷新
  const refreshIntervalRef = useRef(null)

  /**
   * 将后端返回的树结构转换为两级树（namespace -> 实例/程序/Variable）
   * 第一级：namespace
   * 第二级：实例（如sin1）、程序、Variable
   */
  const convertToTreeData = (tree) => {
    const result = []
    
    for (const [namespace, namespaceData] of Object.entries(tree)) {
      const namespaceNode = {
        title: namespace,
        key: `namespace:${namespace}`,
        children: [],
      }
      
      // 添加变量节点（Variable类型）
      const variables = namespaceData.variables || {}
      for (const [varName, varData] of Object.entries(variables)) {
        namespaceNode.children.push({
          title: varName,
          key: `variable:${varData.full_name}`,
          isLeaf: true,
          type: 'variable',
          fullName: varData.full_name,
        })
      }
      
      // 添加实例节点（如sin1、pid1等）
      const instances = namespaceData.instances || {}
      for (const [instanceName, instanceData] of Object.entries(instances)) {
        namespaceNode.children.push({
          title: instanceName,
          key: `instance:${instanceData.full_name}`,
          isLeaf: true,
          type: 'instance',
          fullName: instanceData.full_name,
          attributes: instanceData.attributes || [],
        })
      }
      
      if (namespaceNode.children.length > 0) {
        result.push(namespaceNode)
      }
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
   * 获取实时快照数据
   */
  const fetchSnapshot = async () => {
    try {
      const response = await getRealtimeSnapshot()
      // 只要拿到对象就更新，避免 status 字段异常导致永远不刷新
      if (response && typeof response === 'object') {
        setSnapshotData(response)
      }
    } catch (error) {
      console.error('获取实时快照失败:', error)
      // 不显示错误消息，避免频繁弹窗
    }
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
    
    // 只处理叶子节点
    if (!node.isLeaf) {
      return
    }
    
    // 从key中提取信息
    let fullName = ''
    let type = ''
    let attributes = []
    
    if (key.startsWith('variable:')) {
      fullName = key.replace('variable:', '')
      type = 'variable'
    } else if (key.startsWith('instance:')) {
      fullName = key.replace('instance:', '')
      type = 'instance'
      attributes = node.attributes || []
    }
    
    const newNode = {
      key,
      title: node.title,
      fullName,
      type,
      attributes,
    }
    
    setSelectedNode(newNode)
    
    // 清空写值输入框
    setWriteValues({})
  }

  /**
   * 获取当前值
   */
  const getCurrentValue = (paramName) => {
    if (!snapshotData) {
      return 'N/A'
    }
    
    // 快照数据可能格式：
    // - Redis V1：{ params: { "ns.sin1.out": v, ... }, cycle_count, ... }
    // - 历史接口：{ snapshot: { ...扁平快照 } }（位号在 snapshot 根上）
    // - 扁平：{ "sin1.out": v, ... }（与 params 同级勿与 status 混淆）
    let value
    if (snapshotData.params && Object.prototype.hasOwnProperty.call(snapshotData.params, paramName)) {
      value = snapshotData.params[paramName]
    } else if (
      snapshotData.snapshot &&
      typeof snapshotData.snapshot === 'object' &&
      Object.prototype.hasOwnProperty.call(snapshotData.snapshot, paramName)
    ) {
      value = snapshotData.snapshot[paramName]
    } else if (Object.prototype.hasOwnProperty.call(snapshotData, paramName)) {
      value = snapshotData[paramName]
    } else {
      value = undefined
    }
    
    if (value === undefined || value === null) {
      return 'N/A'
    }
    
    return String(value)
  }

  /**
   * 写值：实例参数
   */
  const handleWriteInstanceParam = async (instanceName, paramName, value) => {
    if (value === '' || value === null || value === undefined) {
      message.warning('请输入要写入的值')
      return
    }
    
    const writeKey = `${instanceName}.${paramName}`
    setWriting({ ...writing, [writeKey]: true })
    
    try {
      // 尝试转换为数字
      let numValue = value
      if (typeof value === 'string') {
        numValue = parseFloat(value)
        if (isNaN(numValue)) {
          message.error('请输入有效的数字')
          return
        }
      }
      
      await patchInstanceParams(instanceName, {
        [paramName]: numValue,
      })
      
      message.success(`写入成功: ${paramName} = ${numValue}`)
      // 清空输入框
      setWriteValues({ ...writeValues, [writeKey]: '' })
    } catch (error) {
      console.error('写值失败:', error)
      message.error(`写值失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      setWriting({ ...writing, [writeKey]: false })
    }
  }

  /**
   * 写值：变量
   */
  const handleWriteVariable = async (variableName, value) => {
    if (value === '' || value === null || value === undefined) {
      message.warning('请输入要写入的值')
      return
    }
    
    setWriting({ ...writing, [variableName]: true })
    
    try {
      // 尝试转换为数字
      let numValue = value
      if (typeof value === 'string') {
        numValue = parseFloat(value)
        if (isNaN(numValue)) {
          message.error('请输入有效的数字')
          return
        }
      }
      
      await patchVariable(variableName, {
        value: numValue,
      })
      
      message.success(`写入成功: ${variableName} = ${numValue}`)
      // 清空输入框
      setWriteValues({ ...writeValues, [variableName]: '' })
    } catch (error) {
      console.error('写值失败:', error)
      message.error(`写值失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      setWriting({ ...writing, [variableName]: false })
    }
  }

  /**
   * 构建表格数据
   */
  const buildTableData = () => {
    if (!selectedNode) {
      return []
    }
    
    if (selectedNode.type === 'variable') {
      // Variable类型：一行表格
      return [
        {
          key: selectedNode.fullName,
          paramName: selectedNode.fullName,
          description: selectedNode.title,
          currentValue: getCurrentValue(selectedNode.fullName),
          type: 'variable',
        },
      ]
    } else if (selectedNode.type === 'instance') {
      // Instance类型：显示该实例的所有属性
      const tableData = []
      const attributes = selectedNode.attributes || []
      
      for (const attr of attributes) {
        tableData.push({
          key: attr.full_name,
          paramName: attr.full_name,
          description: attr.name,
          currentValue: getCurrentValue(attr.full_name),
          type: 'attribute',
          instanceName: selectedNode.fullName,
          attributeName: attr.name,
        })
      }
      
      return tableData
    }
    
    return []
  }

  // 组件挂载时自动加载数据
  useEffect(() => {
    fetchConfigData()
  }, [])

  // 定时刷新快照数据（每秒）
  useEffect(() => {
    // 立即获取一次
    fetchSnapshot()
    
    // 设置定时刷新
    refreshIntervalRef.current = setInterval(() => {
      fetchSnapshot()
    }, 1000)
    
    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current)
      }
    }
  }, [])

  // 表格列定义
  const columns = [
    {
      title: '参数名',
      dataIndex: 'paramName',
      key: 'paramName',
      width: '30%',
      render: (text) => <Text code>{text}</Text>,
    },
    {
      title: '参数描述',
      dataIndex: 'description',
      key: 'description',
      width: '25%',
    },
    {
      title: '当前值',
      dataIndex: 'currentValue',
      key: 'currentValue',
      width: '20%',
      render: (text) => <Text strong style={{ color: '#1890ff' }}>{text}</Text>,
    },
    {
      title: '写值',
      key: 'write',
      width: '25%',
      render: (_, record) => {
        const writeKey = record.type === 'variable' 
          ? record.paramName 
          : `${record.instanceName}.${record.attributeName}`
        
        return (
          <Space>
            <Input
              placeholder="输入值"
              value={writeValues[writeKey] || ''}
              onChange={(e) => {
                setWriteValues({
                  ...writeValues,
                  [writeKey]: e.target.value,
                })
              }}
              style={{ width: 120 }}
              onPressEnter={() => {
                if (record.type === 'variable') {
                  handleWriteVariable(record.paramName, writeValues[writeKey])
                } else {
                  handleWriteInstanceParam(
                    record.instanceName,
                    record.attributeName,
                    writeValues[writeKey]
                  )
                }
              }}
            />
            <Button
              type="primary"
              size="small"
              loading={writing[writeKey]}
              onClick={() => {
                if (record.type === 'variable') {
                  handleWriteVariable(record.paramName, writeValues[writeKey])
                } else {
                  handleWriteInstanceParam(
                    record.instanceName,
                    record.attributeName,
                    writeValues[writeKey]
                  )
                }
              }}
            >
              写入
            </Button>
          </Space>
        )
      },
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={2} style={{ margin: 0 }}>实时数据</Title>
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
        {/* 左侧：两级树（占25%） */}
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

        {/* 右侧：参数表格（占70%） */}
        <Col span={18}>
          <Card title="参数信息" style={{ height: 'calc(100vh - 200px)' }}>
            {selectedNode ? (
              <Table
                columns={columns}
                dataSource={buildTableData()}
                pagination={false}
                size="middle"
                bordered
              />
            ) : (
              <div style={{ padding: '24px', textAlign: 'center', color: '#999' }}>
                请从左侧树中选择一个一级变量节点
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default RealtimeRun
