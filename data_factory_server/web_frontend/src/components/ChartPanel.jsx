import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'

/** 与后端 DEFAULT_PLOT_SCALE_REF 一致：y_plot = y_raw * (100 / ref) */
const PLOT_SCALE_DEFAULT = 100

/**
 * 图表面板：多曲线；可选按 DSL plot_scales 仅缩放绘图纵坐标（不改变导出数据）。
 *
 * @param {Object} props
 * @param {Array} props.data - 快照行
 * @param {string[]} props.variableNames - 要绘制的位号键
 * @param {Record<string, number>} [props.plotScales] - 每位号的满量程 ref，缺省 100
 * @param {'single'|'autoDual'} [props.yAxisMode] - 单 Y 轴或按量级自动双 Y（基于已缩放后的 y）
 */
const ChartPanel = ({ data, variableNames, plotScales = {}, yAxisMode = 'single' }) => {
  const option = useMemo(() => {
    if (!data || !variableNames || data.length === 0) {
      return {}
    }

    const getRef = (varName) => {
      const r = plotScales[varName]
      return r != null && r > 0 ? r : PLOT_SCALE_DEFAULT
    }

    const toPlotY = (raw, varName) => {
      if (raw === undefined || raw === null || Number.isNaN(Number(raw))) return null
      const ref = getRef(varName)
      return Number(raw) * (PLOT_SCALE_DEFAULT / ref)
    }

    const xData = data.map((item) => {
      const x = item.cycle_count !== undefined ? item.cycle_count : item.sim_time
      return x !== undefined && x !== null ? Number(x) : null
    })

    const seriesDataForAxis = variableNames.map((varName) => {
      const ref = getRef(varName)
      const legendName =
        ref !== PLOT_SCALE_DEFAULT ? `${varName} [ref=${ref}]` : varName
      const seriesData = data.map((item, index) => {
        const x = xData[index]
        const raw = item[varName]
        if (x === null || x === undefined || Number.isNaN(x)) return null
        if (raw === undefined || raw === null || Number.isNaN(Number(raw))) return null
        const yPlot = toPlotY(raw, varName)
        return [Number(x), yPlot, Number(raw)]
      })
      return { varName, legendName, seriesData, ref }
    })

    const medians = seriesDataForAxis.map(({ seriesData }) => {
      const ys = seriesData.map((p) => (p ? Math.abs(p[1]) : 0)).filter((y) => y > 0 && Number.isFinite(y))
      if (ys.length === 0) return 0
      const sorted = [...ys].sort((a, b) => a - b)
      return sorted[Math.floor(sorted.length / 2)]
    })

    let axisIndexByVar = {}
    if (yAxisMode === 'autoDual' && variableNames.length >= 2) {
      const indexed = variableNames.map((v, i) => ({ v, i, m: medians[i] }))
      indexed.sort((a, b) => a.m - b.m)
      const mid = Math.floor(indexed.length / 2)
      indexed.forEach((row, idx) => {
        axisIndexByVar[row.v] = idx < mid ? 0 : 1
      })
    } else {
      variableNames.forEach((v) => {
        axisIndexByVar[v] = 0
      })
    }

    const series = seriesDataForAxis.map(({ varName, legendName, seriesData }) => ({
      name: legendName,
      type: 'line',
      data: seriesData,
      yAxisIndex: axisIndexByVar[varName] ?? 0,
      smooth: false,
      symbol: 'none',
      connectNulls: false,
      lineStyle: { width: 1 },
    }))

    const collectYForAxis = (axisIdx) => {
      let minV = Infinity
      let maxV = -Infinity
      series.forEach((serie, si) => {
        if (serie.yAxisIndex !== axisIdx) return
        const pts = seriesDataForAxis[si].seriesData
        pts.forEach((p) => {
          if (!p || p[1] === null || !Number.isFinite(p[1])) return
          minV = Math.min(minV, p[1])
          maxV = Math.max(maxV, p[1])
        })
      })
      return { minV, maxV }
    }

    const padRange = (minV, maxV) => {
      if (!Number.isFinite(minV) || !Number.isFinite(maxV)) {
        return { yMin: -100, yMax: 100 }
      }
      const range = maxV - minV
      let padding
      if (range > 0) padding = range * 0.1
      else if (minV !== 0 || maxV !== 0) padding = Math.max(Math.abs(minV), Math.abs(maxV)) * 0.1
      else padding = 10
      let yMin = minV - padding
      let yMax = maxV + padding
      if (yMax - yMin < 0.01) {
        const center = (minV + maxV) / 2
        const defaultRange = Math.max(Math.abs(center), 1) * 0.1 || 1
        yMin = center - defaultRange
        yMax = center + defaultRange
      }
      return { yMin, yMax }
    }

    const yAxisCount = yAxisMode === 'autoDual' && variableNames.length >= 2 ? 2 : 1
    const yAxes = []
    for (let a = 0; a < yAxisCount; a++) {
      const { minV, maxV } = collectYForAxis(a)
      const { yMin, yMax } = padRange(minV, maxV)
      yAxes.push({
        type: 'value',
        name: yAxisCount > 1 ? (a === 0 ? '轴A(缩放后)' : '轴B(缩放后)') : '缩放后数值',
        nameLocation: 'middle',
        nameGap: 50,
        position: a === 0 ? 'left' : 'right',
        min: Number.isFinite(yMin) ? yMin : undefined,
        max: Number.isFinite(yMax) ? yMax : undefined,
        scale: false,
      })
    }

    const legendNames = seriesDataForAxis.map((s) => s.legendName)

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params) => {
          if (!params || !params.length) return ''
          const lines = [params[0].axisValueLabel]
          params.forEach((p) => {
            const pt = p.data
            if (!pt || pt.length < 3) {
              lines.push(`${p.marker}${p.seriesName}: ${p.value?.[1] ?? '-'}`)
              return
            }
            const [, yPlot, yRaw] = pt
            lines.push(
              `${p.marker}${p.seriesName} 原始=${yRaw} 图上=${typeof yPlot === 'number' ? yPlot.toFixed(4) : yPlot}`,
            )
          })
          return lines.join('<br/>')
        },
      },
      legend: {
        data: legendNames,
        top: 10,
      },
      grid: {
        left: '3%',
        right: yAxisCount > 1 ? '10%' : '4%',
        bottom: '3%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        name: '周期数',
        nameLocation: 'middle',
        nameGap: 30,
      },
      yAxis: yAxes,
      series,
    }
  }, [data, variableNames, plotScales, yAxisMode])

  if (!data || data.length === 0) {
    return <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>暂无数据</div>
  }

  return (
    <div style={{ height: '100%', width: '100%' }}>
      <ReactECharts
        option={option}
        style={{ height: '100%', width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}

export default ChartPanel
