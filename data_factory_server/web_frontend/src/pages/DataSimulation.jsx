import React, { useState, useEffect, useMemo } from 'react'
import { 
  Row, 
  Col, 
  Card, 
  Form, 
  InputNumber, 
  Select, 
  Button, 
  message,
  Spin,
  Space,
  Typography,
  DatePicker,
  Tag,
  Input,
  Modal,
  List,
  Table,
} from 'antd'
import { PlayCircleOutlined, DownloadOutlined } from '@ant-design/icons'
import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { oneDark } from '@codemirror/theme-one-dark'
import { 
  DEFAULT_CYCLE_TIME, 
  DEFAULT_PREVIEW_STEPS, 
  DEFAULT_START_TIME,
  DEFAULT_TOTAL_STEPS,
  COMPACT_FORM_ITEM_LAYOUT,
} from '../utils/constants'
import { 
  getDefaultConfig, 
  getConfigList,
  saveConfig,
  getTemplateList, 
  getExportFormatDefaults,
  simulatePreview,
  exportData,
} from '../services/api'
import ChartPanel from '../components/ChartPanel'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

const { Text } = Typography

/**
 * 数据模拟页面
 *
 * 左侧：DSL 配置编辑器（30%）
 * 右侧：上方配置表单和按钮（50%），下方模拟结果图表（50%）
 * 曲线与导出列仅由 DSL 的 display_args 决定（见后端 get_display_variables）。
 */
const DataSimulation = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)
  const [templates, setTemplates] = useState([])
  const [chartData, setChartData] = useState(null)
  const [stats, setStats] = useState(null)
  const [dslContent, setDslContent] = useState('')
  const [configList, setConfigList] = useState([])
  const [selectedConfig, setSelectedConfig] = useState(null)
  const [saveName, setSaveName] = useState('')
  /** 预览接口返回的全量 plot_scales（位号 -> ref），仅用于图表纵坐标缩放 */
  const [fullPlotScales, setFullPlotScales] = useState({})
  /** 单 Y 轴 | 按量级自动双 Y（基于 DSL 缩放后的 y） */
  const [chartYAxisMode, setChartYAxisMode] = useState('single')

  /** 数据生成弹窗：左侧预设模板名 */
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [selectedPreset, setSelectedPreset] = useState(null)
  /** 右侧可编辑导出格式（与 YAML 解耦） */
  const [exportOpts, setExportOpts] = useState({
    header_rows: 1,
    title_names: '',
    time_format: '%Y/%m/%d %H:%M:%S',
    file_format: 'csv',
    sheet_name: '控制器',
  })

  const plotScalesForChart = useMemo(() => {
    const names = chartData?.variableNames
    if (!fullPlotScales || !names?.length) return {}
    const out = {}
    names.forEach((k) => {
      if (fullPlotScales[k] != null) out[k] = fullPlotScales[k]
    })
    return out
  }, [fullPlotScales, chartData?.variableNames])

  useEffect(() => {
    loadConfigList()
    loadTemplates()
  }, [])

  const loadConfigList = async () => {
    try {
      const response = await getConfigList()
      if (response.status === 'ok' && response.configs && response.configs.length > 0) {
        setConfigList(response.configs)
        const first = response.configs[0]
        setSelectedConfig(first.name)
        setDslContent(first.content)
        form.setFieldsValue({ dsl_content: first.content })
      } else {
        const fallback = await getDefaultConfig()
        if (fallback.status === 'ok') {
          setDslContent(fallback.content)
          form.setFieldsValue({ dsl_content: fallback.content })
        }
      }
    } catch (error) {
      console.error('加载配置列表失败:', error)
      message.error('加载配置列表失败')
    }
  }

  const handleSaveConfig = async () => {
    try {
      if (!dslContent || dslContent.trim() === '') {
        message.error('请输入 DSL 配置')
        return
      }
      if (!saveName || saveName.trim() === '') {
        message.error('请输入要保存的文件名')
        return
      }

      const filename = saveName.trim()
      const response = await saveConfig({
        name: filename,
        content: dslContent,
      })

      if (response.status === 'ok') {
        message.success(`已保存为 ${response.filename}`)
        await loadConfigList()
        setSelectedConfig(response.filename.replace(/\.yaml$/i, ''))
        setSaveName('')
      }
    } catch (error) {
      console.error('保存配置失败:', error)
      message.error(error.response?.data?.detail || '保存配置失败')
    }
  }

  const loadTemplates = async () => {
    try {
      const response = await getTemplateList()
      if (response.templates && response.templates.length > 0) {
        setTemplates(response.templates)
        setSelectedPreset((prev) => prev || response.templates[0])
      }
    } catch (error) {
      console.error('加载模板列表失败:', error)
      message.error('加载模板列表失败')
    }
  }

  const handleSimulate = async () => {
    try {
      const values = await form.validateFields()
      if (!dslContent || dslContent.trim() === '') {
        message.error('请输入 DSL 配置')
        return
      }
      
      setLoading(true)
      setChartData(null)
      setStats(null)
      setFullPlotScales({})

      const totalSteps = values.total_steps || values.preview_steps
      
      let startTime = DEFAULT_START_TIME
      if (values.start_time) {
        if (dayjs.isDayjs(values.start_time)) {
          startTime = values.start_time.valueOf() / 1000
        } else {
          startTime = values.start_time
        }
      }
      
      const response = await simulatePreview({
        dsl_content: dslContent,
        cycle_time: values.cycle_time,
        preview_steps: values.preview_steps,
        start_time: startTime,
        total_steps: totalSteps,
      })

      if (response.status === 'ok') {
        const names = response.variable_names || []
        const displayVars = (response.display_variables || []).filter((k) => names.includes(k))
        setFullPlotScales(response.plot_scales || {})
        setChartData({
          data: response.data,
          variableNames: displayVars,
        })
        setStats({
          generationTime: response.generation_time,
          dataPoints: response.data_points,
          estimatedExportTime: response.estimated_export_time,
          totalSteps: response.total_steps,
        })
        message.success('模拟完成！')
      }
    } catch (error) {
      console.error('模拟失败:', error)
      message.error(error.response?.data?.detail || '模拟失败，请检查 DSL 配置')
    } finally {
      setLoading(false)
    }
  }

  /**
   * 打开导出对话框：校验主表单并拉取当前预设模板的默认导出选项。
   */
  const openExportModal = async () => {
    try {
      await form.validateFields(['cycle_time', 'preview_steps', 'total_steps'])
      if (!dslContent || dslContent.trim() === '') {
        message.error('请输入 DSL 配置')
        return
      }
      if (!templates.length) {
        message.error('暂无模板预设列表，请检查后端')
        return
      }
      const preset = selectedPreset || templates[0]
      const res = await getExportFormatDefaults(preset)
      if (res.status === 'ok' && res.defaults) {
        setExportOpts((o) => ({ ...o, ...res.defaults }))
      }
      setExportModalOpen(true)
    } catch (error) {
      if (error?.errorFields) return
      console.error('打开导出对话框失败:', error)
      message.error(error.response?.data?.detail || '加载导出预设失败')
    }
  }

  const downloadExportResponse = (response, fallbackName) => {
    const name = response.filename || fallbackName
    if (response.file_content != null && response.file_content !== '') {
      const mime = response.mime_type || 'text/csv;charset=utf-8'
      const blob = new Blob([response.file_content], { type: mime })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = name
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
      message.success(`数据生成成功！已下载: ${name}`)
      return
    }
    if (response.file_content_base64) {
      const binary = atob(response.file_content_base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i)
      }
      const mime = response.mime_type || 'application/octet-stream'
      const blob = new Blob([bytes], { type: mime })
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = name
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
      message.success(`数据生成成功！已下载: ${name}`)
      return
    }
    message.success(`数据生成成功！文件路径: ${response.output_path || ''}`)
  }

  /**
   * 弹窗内确认导出：携带 export_format，按格式下载（CSV 文本或 Excel base64）。
   */
  const handleModalExport = async () => {
    if (exportOpts.header_rows === 2 && !String(exportOpts.title_names || '').includes(',')) {
      message.error('TITLE 行数为 2 时，TITLE 名需用英文逗号分隔两段（仅时间列第 1、2 行）')
      return
    }
    if (!templates.length) {
      message.error('暂无模板预设列表，请检查后端')
      return
    }
    try {
      const values = await form.validateFields()
      if (!values.total_steps || values.total_steps <= 0) {
        message.error('请输入总周期数')
        return
      }

      setExportLoading(true)

      let startTime = DEFAULT_START_TIME
      if (values.start_time) {
        if (dayjs.isDayjs(values.start_time)) {
          startTime = values.start_time.valueOf() / 1000
        } else {
          startTime = values.start_time
        }
      }

      const ext =
        exportOpts.file_format === 'xlsx'
          ? '.xlsx'
          : exportOpts.file_format === 'xls'
            ? '.xls'
            : '.csv'
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5)
      const fallbackName = `data_export_${timestamp}${ext}`

      const preset = selectedPreset || templates[0]
      const response = await exportData({
        dsl_content: dslContent,
        steps: values.total_steps,
        template_name: preset,
        output_path: fallbackName,
        cycle_time: values.cycle_time,
        start_time: startTime,
        export_format: {
          header_rows: exportOpts.header_rows,
          title_names: exportOpts.title_names,
          time_format: exportOpts.time_format,
          file_format: exportOpts.file_format,
          sheet_name: exportOpts.sheet_name || '控制器',
        },
      })

      if (response.status === 'ok') {
        downloadExportResponse(response, fallbackName)
        setExportModalOpen(false)
      }
    } catch (error) {
      console.error('数据生成失败:', error)
      message.error(error.response?.data?.detail || '数据生成失败，请检查 DSL 配置')
    } finally {
      setExportLoading(false)
    }
  }

  const exportFormatTableColumns = [
    { title: '属性', dataIndex: 'label', width: 160 },
    {
      title: '值',
      key: 'editor',
      render: (_, record) => record.editor,
    },
  ]

  const exportFormatTableData = [
    {
      key: 'header_rows',
      label: 'TITLE 行数',
      editor: (
        <Select
          style={{ width: '100%' }}
          value={exportOpts.header_rows}
          onChange={(v) => setExportOpts((o) => ({ ...o, header_rows: v }))}
          options={[
            { value: 1, label: '1' },
            { value: 2, label: '2' },
          ]}
        />
      ),
    },
    {
      key: 'title_names',
      label: 'TITLE 名',
      editor: (
        <Input
          value={exportOpts.title_names}
          onChange={(e) => setExportOpts((o) => ({ ...o, title_names: e.target.value }))}
          placeholder={
            exportOpts.header_rows === 2
              ? '英文逗号分隔：时间列第1行,时间列第2行'
              : '时间列第 1 行表头整串'
          }
        />
      ),
    },
    {
      key: 'time_format',
      label: '时间戳格式',
      editor: (
        <Input
          value={exportOpts.time_format}
          onChange={(e) => setExportOpts((o) => ({ ...o, time_format: e.target.value }))}
          placeholder="strftime，如 %Y/%m/%d %H:%M:%S"
        />
      ),
    },
    {
      key: 'file_format',
      label: '文件格式',
      editor: (
        <Select
          style={{ width: '100%' }}
          value={exportOpts.file_format}
          onChange={(v) => setExportOpts((o) => ({ ...o, file_format: v }))}
          options={[
            { value: 'csv', label: 'csv' },
            { value: 'xlsx', label: 'xlsx' },
            { value: 'xls', label: 'xls' },
          ]}
        />
      ),
    },
    {
      key: 'sheet_name',
      label: 'Sheet 名（Excel）',
      editor: (
        <Input
          value={exportOpts.sheet_name}
          onChange={(e) => setExportOpts((o) => ({ ...o, sheet_name: e.target.value }))}
          placeholder="默认：控制器"
        />
      ),
    },
  ]

  return (
    <Row gutter={16} style={{ height: 'calc(100vh - 112px)' }}>
      <Col span={8} style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <Card 
          title="DSL 配置" 
          style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
          bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '16px' }}
        >
          <div style={{ marginBottom: 12, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {configList.map(cfg => (
              <Tag.CheckableTag
                key={cfg.name}
                checked={selectedConfig === cfg.name}
                onChange={() => {
                  setSelectedConfig(cfg.name)
                  setDslContent(cfg.content)
                  form.setFieldsValue({ dsl_content: cfg.content })
                }}
                style={{ padding: '6px 12px', fontSize: 13 }}
              >
                {cfg.name}
              </Tag.CheckableTag>
            ))}
          </div>

          <div style={{ flex: 1, overflow: 'hidden', border: '1px solid #d9d9d9', borderRadius: '4px' }}>
            <CodeMirror
              value={dslContent}
              height="100%"
              extensions={[yaml()]}
              theme={oneDark}
              style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 13 }}
              onChange={(value) => {
                setDslContent(value)
                form.setFieldsValue({ dsl_content: value })
              }}
              basicSetup={{
                lineNumbers: true,
                foldGutter: true,
                dropCursor: false,
                allowMultipleSelections: false,
              }}
            />
          </div>
        </Card>
      </Col>

      <Col span={16} style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div style={{ height: '40%', marginBottom: '16px' }}>
          <Card title="配置参数" style={{ height: '100%' }}>
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                cycle_time: DEFAULT_CYCLE_TIME,
                preview_steps: DEFAULT_PREVIEW_STEPS,
                total_steps: DEFAULT_TOTAL_STEPS,
                start_time: DEFAULT_START_TIME > 0 ? dayjs.unix(DEFAULT_START_TIME) : dayjs(),
              }}
            >
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    label="周期（秒）"
                    name="cycle_time"
                    rules={[{ required: true, message: '请输入周期' }]}
                    {...COMPACT_FORM_ITEM_LAYOUT}
                  >
                    <InputNumber 
                      min={0.001} 
                      step={0.1} 
                      style={{ width: '100%', height: 40 }}
                      size="large"
                      placeholder="执行周期和采样周期"
                    />
                  </Form.Item>
                </Col>

                <Col span={8}>
                  <Form.Item
                    label="总周期数"
                    name="total_steps"
                    {...COMPACT_FORM_ITEM_LAYOUT}
                  >
                    <InputNumber 
                      min={1} 
                      style={{ width: '100%', height: 40 }}
                      size="large"
                      placeholder="用于数据生成"
                    />
                  </Form.Item>
                </Col>

                <Col span={8}>
                  <Form.Item
                    label="模拟绘图周期数"
                    name="preview_steps"
                    rules={[{ required: true, message: '请输入预览周期数' }]}
                    {...COMPACT_FORM_ITEM_LAYOUT}
                  >
                    <InputNumber 
                      min={1} 
                      style={{ width: '100%', height: 40 }}
                      size="large"
                      placeholder="建议 2000"
                    />
                  </Form.Item>
                </Col>
              </Row>

              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item
                    label="起始时间"
                    name="start_time"
                    {...COMPACT_FORM_ITEM_LAYOUT}
                  >
                    <DatePicker 
                      showTime
                      style={{ width: '100%', height: 40 }}
                      size="large"
                      format="YYYY-MM-DD HH:mm:ss"
                    />
                  </Form.Item>
                </Col>

              </Row>

              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item>
                    <Space wrap>
                      <Button
                        type="primary"
                        icon={<PlayCircleOutlined />}
                        onClick={handleSimulate}
                        loading={loading}
                        size="large"
                      >
                        模拟绘图
                      </Button>
                      <Button
                        type="default"
                        icon={<DownloadOutlined />}
                        onClick={openExportModal}
                        size="large"
                      >
                        数据生成
                      </Button>
                    </Space>
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item>
                    <Space wrap style={{ justifyContent: 'flex-end', width: '100%' }}>
                      <Input
                        placeholder="保存为（例如 demo.yaml）"
                        value={saveName}
                        onChange={(e) => setSaveName(e.target.value)}
                        style={{ width: 240, height: 40 }}
                        size="large"
                      />
                      <Button
                        type="primary"
                        size="large"
                        onClick={handleSaveConfig}
                        style={{
                          backgroundColor: '#ff69b4',
                          borderColor: '#ff69b4',
                        }}
                      >
                        保存到服务器
                      </Button>
                    </Space>
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </Card>
        </div>

        <div style={{ height: '50%' }}>
          <Card 
            title="模拟结果" 
            style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
            bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '16px', overflow: 'hidden' }}
            extra={
              <Space wrap align="center">
                <Select
                  size="small"
                  style={{ minWidth: 140 }}
                  value={chartYAxisMode}
                  onChange={setChartYAxisMode}
                  options={[
                    { value: 'single', label: '图表 Y 轴：单轴' },
                    { value: 'autoDual', label: '图表 Y 轴：自动双轴' },
                  ]}
                />
                {stats && (
                  <Text type="secondary">
                    数据点数: {stats.dataPoints} | 生成时间: {stats.generationTime}s | 预估导出时间:{' '}
                    {stats.estimatedExportTime}s
                  </Text>
                )}
              </Space>
            }
          >
            {loading ? (
              <div style={{ textAlign: 'center', padding: '50px' }}>
                <Spin size="large" />
                <div style={{ marginTop: '16px' }}>
                  <Text type="secondary">正在模拟数据，请稍候...</Text>
                </div>
              </div>
            ) : chartData ? (
              <div style={{ flex: 1, minHeight: 0 }}>
              <ChartPanel
                data={chartData.data}
                variableNames={chartData.variableNames}
                plotScales={plotScalesForChart}
                yAxisMode={chartYAxisMode}
              />
              </div>
            ) : (
              <div style={{ 
                textAlign: 'center', 
                padding: '50px',
                color: '#999',
              }}>
                请配置参数并点击&quot;模拟绘图&quot;按钮
              </div>
            )}
          </Card>
        </div>
      </Col>

      <Modal
        title="数据生成 — 导出格式"
        open={exportModalOpen}
        onCancel={() => setExportModalOpen(false)}
        width={880}
        footer={[
          <Button key="cancel" onClick={() => setExportModalOpen(false)}>
            取消
          </Button>,
          <Button
            key="export"
            type="primary"
            icon={<DownloadOutlined />}
            loading={exportLoading}
            onClick={handleModalExport}
          >
            导出
          </Button>,
        ]}
        destroyOnClose={false}
      >
        <Row gutter={16}>
          <Col span={7}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              模板预设（仅填充右侧默认值）
            </Text>
            <List
              size="small"
              bordered
              style={{ maxHeight: 360, overflow: 'auto' }}
              dataSource={templates}
              locale={{ emptyText: '暂无模板' }}
              renderItem={(item) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    background: selectedPreset === item ? '#e6f7ff' : undefined,
                  }}
                  onClick={async () => {
                    setSelectedPreset(item)
                    try {
                      const res = await getExportFormatDefaults(item)
                      if (res.status === 'ok' && res.defaults) {
                        setExportOpts((o) => ({ ...o, ...res.defaults }))
                      }
                    } catch (err) {
                      message.error(err.response?.data?.detail || '加载预设失败')
                    }
                  }}
                >
                  {item}
                </List.Item>
              )}
            />
          </Col>
          <Col span={17}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              导出选项（与 YAML 解耦，以下为准）
            </Text>
            <Table
              size="small"
              pagination={false}
              columns={exportFormatTableColumns}
              dataSource={exportFormatTableData}
            />
          </Col>
        </Row>
      </Modal>
    </Row>
  )
}

export default DataSimulation
