import React, { useState } from 'react'
import { 
  Row, 
  Col, 
  Card, 
  Button, 
  Input,
  message,
  Typography,
  Space,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'
import { 
  loadRealtimeConfig,
  getRealtimeSnapshot,
  getRealtimeConfigFromRedis,
} from '../services/api'

const { Title } = Typography
const { TextArea } = Input

/**
 * 调试页面
 * 
 * 左侧：DSL配置输入 + namespace输入 + 添加按钮
 * 右侧：实时数据编辑框 + 组态信息编辑框 + 刷新按钮
 */
const RealtimeDev = () => {
  const [dslContent, setDslContent] = useState('')
  const [namespace, setNamespace] = useState('')
  const [loading, setLoading] = useState(false)
  const [snapshotData, setSnapshotData] = useState('')
  const [configData, setConfigData] = useState('')
  const [snapshotLoading, setSnapshotLoading] = useState(false)
  const [configLoading, setConfigLoading] = useState(false)

  /**
   * 添加DSL配置
   */
  const handleAddConfig = async () => {
    if (!dslContent || dslContent.trim() === '') {
      message.error('请输入 DSL 配置内容')
      return
    }

    setLoading(true)
    try {
      const response = await loadRealtimeConfig({
        dsl_content: dslContent,
        namespace: namespace.trim() || undefined,
      })
      
      if (response.status === 'ok') {
        message.success('配置添加成功')
        setDslContent('') // 清空输入框
        setNamespace('') // 清空命名空间
      } else {
        message.error('配置添加失败')
      }
    } catch (error) {
      console.error('添加配置失败:', error)
      message.error(`添加配置失败: ${error.response?.data?.detail || error.message}`)
    } finally {
      setLoading(false)
    }
  }

  /**
   * 刷新实时数据
   */
  const handleRefreshSnapshot = async () => {
    setSnapshotLoading(true)
    try {
      const data = await getRealtimeSnapshot()
      setSnapshotData(JSON.stringify(data, null, 2))
      message.success('实时数据已刷新')
    } catch (error) {
      console.error('获取实时数据失败:', error)
      message.error(`获取实时数据失败: ${error.response?.data?.detail || error.message}`)
      setSnapshotData('')
    } finally {
      setSnapshotLoading(false)
    }
  }

  /**
   * 刷新组态信息
   */
  const handleRefreshConfig = async () => {
    setConfigLoading(true)
    try {
      const data = await getRealtimeConfigFromRedis()
      setConfigData(JSON.stringify(data, null, 2))
      message.success('组态信息已刷新')
    } catch (error) {
      console.error('获取组态信息失败:', error)
      message.error(`获取组态信息失败: ${error.response?.data?.detail || error.message}`)
      setConfigData('')
    } finally {
      setConfigLoading(false)
    }
  }

  return (
    <div>
      <Title level={2}>调试</Title>
      
      <Row gutter={16}>
        {/* 左侧：DSL配置输入 */}
        <Col span={12}>
          <Card 
            title="添加DSL配置" 
            style={{ height: '100%' }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <div>
                <div style={{ marginBottom: 8 }}>
                  <strong>DSL内容：</strong>
                </div>
                <CodeMirror
                  value={dslContent}
                  height="400px"
                  extensions={[yaml()]}
                  theme={oneDark}
                  onChange={(value) => setDslContent(value)}
                  style={{ fontSize: '14px' }}
                />
              </div>
              
              <div>
                <div style={{ marginBottom: 8 }}>
                  <strong>命名空间（可选）：</strong>
                </div>
                <Input
                  placeholder="输入命名空间，例如：ns1"
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                  allowClear
                />
              </div>
              
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleAddConfig}
                loading={loading}
                block
              >
                添加配置
              </Button>
            </Space>
          </Card>
        </Col>

        {/* 右侧：实时数据和组态信息 */}
        <Col span={12}>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* 实时数据 */}
            <Card 
              title="实时数据" 
              extra={
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  onClick={handleRefreshSnapshot}
                  loading={snapshotLoading}
                  size="small"
                >
                  刷新
                </Button>
              }
            >
              <TextArea
                value={snapshotData}
                placeholder="点击刷新按钮获取实时数据..."
                rows={12}
                readOnly
                style={{ fontFamily: 'monospace', fontSize: '12px' }}
              />
            </Card>

            {/* 组态信息 */}
            <Card 
              title="组态信息" 
              extra={
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  onClick={handleRefreshConfig}
                  loading={configLoading}
                  size="small"
                >
                  刷新
                </Button>
              }
            >
              <TextArea
                value={configData}
                placeholder="点击刷新按钮获取组态信息..."
                rows={12}
                readOnly
                style={{ fontFamily: 'monospace', fontSize: '12px' }}
              />
            </Card>
          </Space>
        </Col>
      </Row>
    </div>
  )
}

export default RealtimeDev
