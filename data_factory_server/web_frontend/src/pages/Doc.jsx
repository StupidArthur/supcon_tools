import React, { useState, useEffect } from 'react'
import { Row, Col, Card, Tree, Spin, message, Typography } from 'antd'
import { DatabaseOutlined, FunctionOutlined } from '@ant-design/icons'
import MarkdownViewer from '../components/MarkdownViewer'
import { 
  getProgramsList, 
  getFunctionsList, 
  getProgramDoc, 
  getFunctionDoc 
} from '../services/api'

const { Title } = Typography

/**
 * 文档页面
 * 
 * 左侧：二级树形结构（Program和Function）
 * 右侧：显示选中的算法或函数的文档
 */
const Doc = () => {
  const [loading, setLoading] = useState(true)
  const [treeData, setTreeData] = useState([])
  const [selectedKey, setSelectedKey] = useState(null)
  const [docContent, setDocContent] = useState('')
  const [docLoading, setDocLoading] = useState(false)

  useEffect(() => {
    loadTreeData()
  }, [])

  /**
   * 加载树形结构数据
   */
  const loadTreeData = async () => {
    try {
      setLoading(true)
      const [programsRes, functionsRes] = await Promise.all([
        getProgramsList(),
        getFunctionsList(),
      ])

      const programs = programsRes.programs || []
      const functions = functionsRes.functions || []

      // 构建树形数据
      const tree = [
        {
          title: 'Program',
          key: 'program',
          icon: <DatabaseOutlined />,
          children: programs.map(name => ({
            title: name,
            key: `program-${name}`,
            isLeaf: true,
          })),
        },
        {
          title: 'Function',
          key: 'function',
          icon: <FunctionOutlined />,
          children: functions.map(name => ({
            title: name,
            key: `function-${name}`,
            isLeaf: true,
          })),
        },
      ]

      setTreeData(tree)
    } catch (error) {
      console.error('加载文档列表失败:', error)
      message.error('加载文档列表失败')
    } finally {
      setLoading(false)
    }
  }

  /**
   * 处理树节点选择
   */
  const handleSelect = async (selectedKeys) => {
    if (selectedKeys.length === 0) {
      setSelectedKey(null)
      setDocContent('')
      return
    }

    const key = selectedKeys[0]
    setSelectedKey(key)

    // 解析key，判断是program还是function
    if (key.startsWith('program-')) {
      const programName = key.replace('program-', '')
      await loadProgramDoc(programName)
    } else if (key.startsWith('function-')) {
      const functionName = key.replace('function-', '')
      await loadFunctionDoc(functionName)
    }
  }

  /**
   * 加载程序文档
   */
  const loadProgramDoc = async (programName) => {
    try {
      setDocLoading(true)
      const response = await getProgramDoc(programName)
      if (response.status === 'ok') {
        // 组合文档和参数表格
        let content = ''
        
        // 如果doc存在，直接使用（doc中已包含标题）
        if (response.doc) {
          content = response.doc.trim()
        } else {
          // 如果没有doc，使用chinese_name和name作为标题
          content = `# ${response.chinese_name} (${response.name})\n\n`
        }
        
        // 添加参数列表（如果存在）
        if (response.params_table) {
          content += `\n\n## 参数列表\n\n${response.params_table}\n`
        }
        
        setDocContent(content)
      }
    } catch (error) {
      console.error('加载程序文档失败:', error)
      message.error(`加载程序 ${programName} 的文档失败`)
      setDocContent('# 文档加载失败\n\n请稍后重试。')
    } finally {
      setDocLoading(false)
    }
  }

  /**
   * 加载函数文档
   */
  const loadFunctionDoc = async (functionName) => {
    try {
      setDocLoading(true)
      const response = await getFunctionDoc(functionName)
      if (response.status === 'ok') {
        // 组合文档和参数表格
        let content = ''
        
        // 如果doc存在，直接使用（doc中已包含标题）
        if (response.doc) {
          content = response.doc.trim()
        } else {
          // 如果没有doc，使用chinese_name和name作为标题
          content = `# ${response.chinese_name} (${response.name})\n\n`
        }
        
        // 添加参数列表（如果存在）
        if (response.params_table) {
          content += `\n\n## 参数列表\n\n${response.params_table}\n`
        }
        
        setDocContent(content)
      }
    } catch (error) {
      console.error('加载函数文档失败:', error)
      message.error(`加载函数 ${functionName} 的文档失败`)
      setDocContent('# 文档加载失败\n\n请稍后重试。')
    } finally {
      setDocLoading(false)
    }
  }

  return (
    <Row gutter={16} style={{ height: 'calc(100vh - 160px)' }}>
      {/* 左侧树形结构 */}
      <Col span={6} style={{ height: '100%', overflow: 'auto' }}>
        <Card title="文档目录" style={{ height: '100%' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '50px' }}>
              <Spin size="large" />
            </div>
          ) : (
            <Tree
              showIcon
              selectedKeys={selectedKey ? [selectedKey] : []}
              onSelect={handleSelect}
              treeData={treeData}
              style={{ background: 'transparent' }}
            />
          )}
        </Card>
      </Col>

      {/* 右侧文档内容 */}
      <Col span={18} style={{ height: '100%', overflow: 'auto' }}>
        <Card 
          title={selectedKey ? '文档详情' : '请选择左侧文档项'} 
          style={{ height: '100%' }}
        >
          {docLoading ? (
            <div style={{ textAlign: 'center', padding: '50px' }}>
              <Spin size="large" />
            </div>
          ) : docContent ? (
            <MarkdownViewer content={docContent} />
          ) : (
            <div style={{ 
              textAlign: 'center', 
              padding: '50px',
              color: '#999',
            }}>
              请从左侧选择要查看的算法或函数文档
            </div>
          )}
        </Card>
      </Col>
    </Row>
  )
}

export default Doc
