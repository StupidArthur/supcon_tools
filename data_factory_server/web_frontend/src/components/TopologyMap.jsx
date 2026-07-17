import React from 'react';
import ReactECharts from 'echarts-for-react';

/**
 * 系统拓扑图组件
 * 
 * @param {Object} props
 * @param {Object} props.diagnosticData - 诊断摘要数据
 * @param {Object} props.detailedDiagnostics - 详细诊断数据
 */
const TopologyMap = ({ diagnosticData, detailedDiagnostics }) => {
    if (!diagnosticData) return null;

    const servicesStatus = diagnosticData.services_status || {};

    // 识别所有引擎
    const engines = Object.keys(servicesStatus)
        .filter(name => name.startsWith('engine'))
        .map(name => ({
            id: name,
            name: name.split('.').length > 1 ? name.split('.')[1] : 'default',
            status: diagnosticData[`${name}_running`] ? 'healthy' : 'stopped'
        }));

    const nodes = [
        {
            id: 'config_server',
            name: 'Config Server',
            category: 0,
            symbolSize: 60,
            itemStyle: { color: '#722ed1' },
            label: { show: true, position: 'bottom' }
        },
        {
            id: 'redis_bus',
            name: 'Redis Data Bus (V2)',
            category: 1,
            symbolSize: 80,
            itemStyle: { color: '#f5222d' },
            label: { show: true, position: 'bottom' }
        },
        {
            id: 'storage',
            name: 'Storage Service',
            category: 2,
            symbolSize: 60,
            itemStyle: { color: '#52c41a' },
            label: { show: true, position: 'bottom' }
        },
        {
            id: 'opcua',
            name: 'OPCUA Server',
            category: 2,
            symbolSize: 60,
            itemStyle: { color: '#1890ff' },
            label: { show: true, position: 'bottom' }
        }
    ];

    const links = [];

    // 添加引擎节点及连线
    engines.forEach((engine, index) => {
        const engineNodeId = `engine_${engine.id}`;
        nodes.push({
            id: engineNodeId,
            name: `Engine [${engine.name}]`,
            category: 3,
            symbolSize: 50,
            itemStyle: { color: engine.status === 'healthy' ? '#13c2c2' : '#bfbfbf' },
            label: { show: true, position: 'bottom' }
        });

        // Config -> Engine
        links.push({
            source: 'config_server',
            target: engineNodeId,
            lineStyle: { type: 'dashed', curveness: 0.2 }
        });

        // Engine -> Redis
        links.push({
            source: engineNodeId,
            target: 'redis_bus',
            label: { show: false, formatter: 'Push' },
            lineStyle: { width: 3, curveness: -0.1 }
        });
    });

    // Redis -> Consumers
    links.push({ source: 'redis_bus', target: 'storage', lineStyle: { width: 3 } });
    links.push({ source: 'redis_bus', target: 'opcua', lineStyle: { width: 3 } });

    const option = {
        title: {
            text: '系统架构拓扑',
            subtext: '实时引擎与数据流动',
            top: 'top',
            left: 'left'
        },
        tooltip: {},
        legend: [
            {
                data: ['Management', 'Data Bus', 'Consumer', 'Engine'],
                orient: 'vertical',
                right: 10,
                top: 20
            }
        ],
        series: [
            {
                type: 'graph',
                layout: 'force',
                data: nodes,
                links: links,
                categories: [
                    { name: 'Management' },
                    { name: 'Data Bus' },
                    { name: 'Consumer' },
                    { name: 'Engine' }
                ],
                roam: true,
                label: {
                    position: 'right',
                    formatter: '{b}'
                },
                force: {
                    repulsion: 1000,
                    edgeLength: 150
                },
                lineStyle: {
                    color: 'source',
                    curveness: 0.1,
                    opacity: 0.6
                },
                emphasis: {
                    focus: 'adjacency',
                    lineStyle: {
                        width: 5
                    }
                }
            }
        ]
    };

    return (
        <div style={{ height: '400px', width: '100%' }}>
            <ReactECharts
                option={option}
                style={{ height: '100%', width: '100%' }}
                notMerge={true}
            />
        </div>
    );
};

export default TopologyMap;
