import React, { useState, useEffect } from 'react'
import { Spin, message } from 'antd'
import axios from 'axios'
import MarkdownViewer from '../components/MarkdownViewer'
import { API_BASE_URL } from '../utils/constants'

/**
 * 首页组件
 * 
 * 显示项目的 README.md 内容
 */
const Home = () => {
  const [readmeContent, setReadmeContent] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadReadme()
  }, [])

  const loadReadme = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${API_BASE_URL}/readme`)
      if (response.data.status === 'ok') {
        setReadmeContent(response.data.content)
      } else {
        setReadmeContent('# Data Factory Next\n\n欢迎使用 Data Factory Next！')
      }
    } catch (error) {
      console.error('加载 README 失败:', error)
      message.error('加载 README 失败')
      setReadmeContent('# Data Factory Next\n\n欢迎使用 Data Factory Next！')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '50px' }}>
        <Spin size="large" />
      </div>
    )
  }

  return <MarkdownViewer content={readmeContent} />
}

export default Home

