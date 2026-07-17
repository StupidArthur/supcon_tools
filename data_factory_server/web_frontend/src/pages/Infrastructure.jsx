import React, { useState, useEffect } from 'react'
import { Typography, Card, Button, message, Alert, Space, Divider } from 'antd'
import { SaveOutlined, ReloadOutlined, DatabaseOutlined, CodeOutlined } from '@ant-design/icons'
import { getManifestContent, updateManifestContent, reloadServices } from '../services/api'
import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'

const { Title, Text } = Typography

/**
 * 基础设施配置页面
 * 允许用户直接编辑 engines_manifest.yaml 并触发热重载
 */
const Infrastructure = () => {
    const [content, setContent] = useState('')
    const [originalContent, setOriginalContent] = useState('')
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [reloading, setReloading] = useState(false)
    const [error, setError] = useState(null)

    // 加载 Manifest
    const loadManifest = async () => {
        setLoading(true)
        setError(null)
        try {
            const resp = await getManifestContent()
            if (resp.status === 'ok') {
                setContent(resp.content || '')
                setOriginalContent(resp.content || '')
            } else {
                message.error('加载配置失败')
            }
        } catch (err) {
            console.error(err)
            setError(err.message || '加载配置失败')
        } finally {
            setLoading(false)
        }
    }

    // 保存 Manifest
    const handleSave = async () => {
        setSaving(true)
        try {
            const resp = await updateManifestContent(content)
            if (resp.status === 'ok') {
                message.success('配置已保存')
                setOriginalContent(content)
            }
        } catch (err) {
            console.error(err)
            message.error(`保存失败: ${err.response?.data?.detail || err.message}`)
        } finally {
            setSaving(false)
        }
    }

    // 重载服务
    const handleReload = async () => {
        if (content !== originalContent) {
            message.warning('请先保存配置')
            return
        }

        setReloading(true)
        try {
            const resp = await reloadServices()
            if (resp.status === 'ok') {
                message.success('服务重载成功！')
            }
        } catch (err) {
            console.error(err)
            message.error(`重载失败: ${err.response?.data?.detail || err.message}`)
        } finally {
            setReloading(false)
        }
    }

    useEffect(() => {
        loadManifest()
    }, [])

    const hasChanges = content !== originalContent

    return (
        <div style={{ padding: '24px', height: 'calc(100vh - 64px)', display: 'flex', flexDirection: 'column' }}>
            <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Space direction="vertical" size={2}>
                    <Title level={2} style={{ margin: 0 }}>引擎管理与编排</Title>
                    <Text type="secondary">编排 engines_manifest.yaml 以动态启动/聚合多个仿真引擎与回放引擎</Text>
                </Space>
                <Space>
                    <Button
                        icon={<DatabaseOutlined />}
                        onClick={loadManifest}
                        loading={loading}
                    >
                        同步云端
                    </Button>
                    <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={handleSave}
                        loading={saving}
                        disabled={!hasChanges}
                    >
                        保存配置
                    </Button>
                    <Button
                        type="primary"
                        danger
                        icon={<ReloadOutlined />}
                        onClick={handleReload}
                        loading={reloading}
                    >
                        全量热重载
                    </Button>
                </Space>
            </div>

            {error && (
                <Alert
                    message="配置错误"
                    description={error}
                    type="error"
                    showIcon
                    style={{ marginBottom: '16px' }}
                />
            )}

            <div style={{ display: 'flex', flex: 1, gap: '16px', overflow: 'hidden' }}>
                {/* 编辑器区域 */}
                <Card
                    title={<Space><CodeOutlined /> 编排脚本 (YAML)</Space>}
                    style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
                    bodyStyle={{ flex: 1, padding: 0, overflow: 'hidden' }}
                    loading={loading && !content}
                >
                    <CodeMirror
                        value={content}
                        height="100%"
                        theme={oneDark}
                        extensions={[yaml()]}
                        onChange={(value) => setContent(value)}
                        style={{ fontSize: '14px', height: 'calc(100vh - 280px)' }}
                    />
                </Card>

                {/* 辅助说明区域 */}
                <Card
                    title="配置指南"
                    style={{ width: '320px', overflowY: 'auto' }}
                >
                    <Text strong>多引擎支持</Text>
                    <div style={{ fontSize: '13px', marginTop: '8px' }}>
                        支持同时运行多个 Simulation 和 Playback 引擎。所有引擎产生的数据将在 Hash 记录中按 <Text code>engine_id</Text> 区分。
                    </div>

                    <Divider style={{ margin: '12px 0' }} />

                    <Text strong>回放配置示例</Text>
                    <pre style={{ backgroundColor: '#f5f5f5', padding: '8px', borderRadius: '4px', fontSize: '11px', marginTop: '8px' }}>
                        {`- id: my_playback
  type: playback
  source: data/history.xlsx
  time_col: T_TAG`}
                    </pre>

                    <Divider style={{ margin: '12px 0' }} />

                    <Text strong>热重载说明</Text>
                    <div style={{ fontSize: '12px', marginTop: '8px', color: '#666' }}>
                        点击“全量热重载”后，系统将：
                        <ul style={{ paddingLeft: '20px' }}>
                            <li>对比当前运行引擎与 Manifest</li>
                            <li>停止已移除的引擎</li>
                            <li>启动新增的引擎</li>
                            <li>更新存储与 OPCUA 的频率</li>
                        </ul>
                    </div>
                </Card>
            </div>
        </div>
    )
}

export default Infrastructure
