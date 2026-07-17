/**
 * API 服务封装
 * 
 * 统一管理所有 API 调用
 */

import axios from 'axios'
import { API_BASE_URL } from '../utils/constants'

// 创建 axios 实例
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 5分钟超时（模拟可能需要较长时间）
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * 健康检查
 */
export const healthCheck = async () => {
  const response = await apiClient.get('/health')
  return response.data
}

/**
 * 获取默认 DSL 配置
 */
export const getDefaultConfig = async () => {
  const response = await apiClient.get('/config/default')
  return response.data
}

/**
 * 获取所有可用的 DSL 配置列表（config 目录下的 yaml）
 */
export const getConfigList = async () => {
  const response = await apiClient.get('/config/list')
  return response.data
}

/**
 * 保存 DSL 配置到服务器
 * @param {Object} params
 * @param {string} params.name 文件名（可不带 .yaml 后缀）
 * @param {string} params.content YAML 内容
 */
export const saveConfig = async (params) => {
  const response = await apiClient.post('/config/save', params)
  return response.data
}

/**
 * 获取模板列表
 */
export const getTemplateList = async () => {
  const response = await apiClient.get('/templates/list')
  return response.data
}

/**
 * 获取某 YAML 模板对应的导出对话框默认值（仅预设，实际导出以 export_format 为准）
 * @param {string} templateName - 模板名（不含 .yaml）
 */
export const getExportFormatDefaults = async (templateName) => {
  const enc = encodeURIComponent(templateName)
  const response = await apiClient.get(`/export/format-defaults/${enc}`)
  return response.data
}

/**
 * 模拟预览
 * 
 * @param {Object} params - 预览参数
 * @param {string} params.dsl_content - DSL YAML 内容
 * @param {number} params.cycle_time - 执行周期（秒）
 * @param {number} params.preview_steps - 预览周期数
 * @param {number} params.start_time - 起始时间
 * @param {string} params.time_format - 时间格式
 */
export const simulatePreview = async (params) => {
  const response = await apiClient.post('/simulate/preview', params)
  return response.data
}

/**
 * 导出数据
 *
 * @param {Object} params - 导出参数
 * @param {string} [params.config_path] - 配置文件路径
 * @param {number} params.steps - 总周期数
 * @param {string} [params.template_name] - 无 export_format 时用于 YAML；有 export_format 时仅记录
 * @param {string} params.output_path - 输出文件路径
 * @param {string[]} [params.selected_variables] - 仅导出这些列；不传则按 DSL 非空 display_args 对应列导出
 * @param {Object} [params.export_format] - { header_rows, title_names, time_format, file_format, sheet_name? }
 */
export const exportData = async (params) => {
  const response = await apiClient.post('/export/run', params)
  return response.data
}

/**
 * 获取 README.md 内容
 */
export const getReadme = async () => {
  const response = await apiClient.get('/readme')
  return response.data
}

/**
 * 获取所有程序（算法和模型）列表
 */
export const getProgramsList = async () => {
  const response = await apiClient.get('/docs/programs/list')
  return response.data
}

/**
 * 获取所有函数列表
 */
export const getFunctionsList = async () => {
  const response = await apiClient.get('/docs/functions/list')
  return response.data
}

/**
 * 获取指定程序的文档信息
 * @param {string} programName - 程序名称
 */
export const getProgramDoc = async (programName) => {
  const response = await apiClient.get(`/docs/program/${programName}`)
  return response.data
}

/**
 * 获取指定函数的文档信息
 * @param {string} functionName - 函数名称
 */
export const getFunctionDoc = async (functionName) => {
  const response = await apiClient.get(`/docs/function/${functionName}`)
  return response.data
}

/**
 * 加载实时配置
 * @param {Object} params
 * @param {string} params.dsl_content - DSL YAML 内容（优先使用）
 * @param {string} params.config_path - 配置文件路径（当dsl_content为空时使用）
 * @param {string} params.namespace - 命名空间（可选）
 */
export const loadRealtimeConfig = async (params) => {
  const response = await apiClient.post('/realtime/configs', params)
  return response.data
}

/**
 * 获取实时数据快照
 */
export const getRealtimeSnapshot = async () => {
  const response = await apiClient.get('/realtime/snapshot')
  return response.data
}

/**
 * 获取服务状态（包含组态信息）
 */
export const getServicesStatus = async () => {
  const response = await apiClient.get('/services/status')
  return response.data
}

/**
 * 获取实时组态信息（实例列表、变量列表等）
 */
export const getRealtimeConfig = async () => {
  const response = await apiClient.get('/realtime/config')
  return response.data
}

/**
 * 从Redis获取实时组态信息（用于组态页面，包含三级树结构）
 */
export const getRealtimeConfigFromRedis = async () => {
  const response = await apiClient.get('/realtime/config/redis')
  return response.data
}

/**
 * 获取诊断信息
 */
export const getDiagnosticInfo = async () => {
  const response = await apiClient.get('/services/diagnostic')
  return response.data
}

/**
 * 获取详细诊断信息（从Redis读取）
 */
export const getDetailedDiagnostics = async () => {
  const response = await apiClient.get('/services/diagnostic/detail')
  return response.data
}

/**
 * 查询历史数据（固定采样点数）
 * @param {Object} params
 * @param {string} params.param_name - 参数名称（位号名）
 * @param {string} params.end_time - 终止时间（ISO格式字符串，可选）
 * @param {number} params.time_length - 时间长度（秒），默认1200秒
 * @param {number} params.sample_points - 采样点数，默认1200点
 */
export const queryHistoryData = async (params) => {
  const response = await apiClient.post('/history/query', params)
  return response.data
}

/**
 * 修改实例参数值
 * @param {string} instanceName - 实例名称
 * @param {Object} params - 参数对象，例如 { param_name: value }
 */
export const patchInstanceParams = async (instanceName, params) => {
  const response = await apiClient.patch(`/realtime/instances/${instanceName}/params`, { params })
  return response.data
}

/**
 * 修改变量值
 * @param {string} variableName - 变量名称
 * @param {Object} data - 修改数据，例如 { value: 123 } 或 { expression: "..." }
 */
export const patchVariable = async (variableName, data) => {
  const response = await apiClient.patch(`/realtime/variables/${variableName}`, data)
  return response.data
}


/**
 * 获取基础设施配置文件 (engines_manifest.yaml)
 */
export const getManifestContent = async () => {
  const response = await apiClient.get('/config/manifest')
  return response.data
}

/**
 * 更新基础设施配置文件
 * @param {string} content YAML内容
 */
export const updateManifestContent = async (content) => {
  const response = await apiClient.post('/config/manifest', { content })
  return response.data
}

/**
 * 热重载基础设施服务
 */
export const reloadServices = async () => {
  const response = await apiClient.post('/services/reload')
  return response.data
}
