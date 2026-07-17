import React, { useState, useEffect } from 'react'
import { Select, message } from 'antd'
import { getEnginesList } from '../services/api'

const EngineSelect = ({ value, onChange, style }) => {
    const [engines, setEngines] = useState([])
    const [loading, setLoading] = useState(false)

    const loadEngines = async () => {
        setLoading(true)
        try {
            const resp = await getEnginesList()
            if (resp.status === 'ok') {
                const list = resp.engines || []
                // 如果没有默认引擎，尝试自动补全一个 default 选项（针对纯单机启动）
                // 但通过 getEnginesList 已经能拿到所有运行中的
                if (list.length === 0) {
                    list.push({ id: 'default', type: 'simulation', status: 'unknown' })
                }
                setEngines(list)

                // 如果当前没有选中值，默认选第一个
                if (!value && list.length > 0) {
                    onChange(list[0].id)
                }
            }
        } catch (error) {
            console.error('Failed to load engines:', error)
            message.error('无法加载引擎列表')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        loadEngines()
    }, [])

    return (
        <Select
            value={value}
            onChange={onChange}
            style={{ width: 200, ...style }}
            loading={loading}
            placeholder="Select Engine"
            options={engines.map(e => ({
                label: `${e.id} (${e.type})`,
                value: e.id
            }))}
        />
    )
}

export default EngineSelect
