import React from 'react'
import { Layout, Menu } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  HomeOutlined,
  DatabaseOutlined,
  PlayCircleOutlined,
  FileTextOutlined,
  MonitorOutlined,
  SettingOutlined,
} from '@ant-design/icons'

const { Header: AntHeader } = Layout

// 图标映射
const iconMap = {
  HomeOutlined: HomeOutlined,
  DatabaseOutlined: DatabaseOutlined,
  PlayCircleOutlined: PlayCircleOutlined,
  FileTextOutlined: FileTextOutlined,
  MonitorOutlined: MonitorOutlined,
  SettingOutlined: SettingOutlined,
}

/**
 * 顶部导航栏组件
 * 使用 React Router 进行导航
 */
const Header = ({ menuItems, currentPage }) => {
  const navigate = useNavigate()
  const location = useLocation()

  const handleMenuClick = ({ key }) => {
    const menuItem = menuItems.find(item => item.key === key)
    if (menuItem && menuItem.path) {
      navigate(menuItem.path)
    }
  }

  // 根据当前路径确定选中的菜单项
  const selectedKeys = [currentPage]

  // 转换菜单项格式，添加图标
  const items = menuItems.map(item => {
    const IconComponent = iconMap[item.icon] || HomeOutlined
    return {
      key: item.key,
      icon: <IconComponent />,
      label: item.label,
    }
  })

  return (
    <AntHeader style={{
      display: 'flex',
      alignItems: 'center',
      background: '#001529',
      padding: '0 24px',
    }}>
      <div
        style={{
          color: '#fff',
          fontSize: '20px',
          fontWeight: 'bold',
          marginRight: '48px',
          cursor: 'pointer',
        }}
        onClick={() => navigate('/')}
      >
        Data Factory Next
      </div>
      <Menu
        theme="dark"
        mode="horizontal"
        selectedKeys={selectedKeys}
        items={items}
        onClick={handleMenuClick}
        style={{ flex: 1, minWidth: 0 }}
      />
    </AntHeader>
  )
}

export default Header
