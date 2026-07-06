"""
图表管理模块
负责图表的初始化和更新
"""
from typing import Dict, Any, List
from matplotlib.figure import Figure
from matplotlib.axes import Axes


class ChartManager:
    """图表管理器"""
    
    @staticmethod
    def init_chart(figure: Figure) -> tuple[Axes, Axes]:
        """
        初始化图表
        
        Args:
            figure: matplotlib Figure对象
        
        Returns:
            (ax1, ax2): 主y轴和次y轴
        """
        figure.clear()
        ax1 = figure.add_subplot(111)
        
        # 创建第二个y轴（用于MV）
        ax2 = ax1.twinx()
        
        # 设置标签和颜色
        ax1.set_xlabel('模拟时间 (秒)', fontsize=12)
        ax1.set_ylabel('SV / PV', fontsize=12, color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        
        ax2.set_ylabel('MV', fontsize=12, color='orange')
        ax2.tick_params(axis='y', labelcolor='orange')
        
        ax1.grid(True, alpha=0.3)
        ax1.set_title('PID控制曲线', fontsize=14, fontweight='bold')
        
        return ax1, ax2
    
    @staticmethod
    def update_chart(ax1: Axes, ax2: Axes, canvas, data_records: List[Dict[str, Any]]):
        """
        更新图表
        
        Args:
            ax1: 主y轴
            ax2: 次y轴
            canvas: matplotlib画布
            data_records: 数据记录列表
        """
        if not data_records:
            return
        
        # 清空图表
        ax1.clear()
        ax2.clear()
        
        # 提取数据
        sim_times = [r['sim_time'] for r in data_records]
        sv_values = [r.get('pid.sv', 0) for r in data_records]
        pv_values = [r.get('pid.pv', 0) for r in data_records]
        mv_values = [r.get('pid.mv', 0) for r in data_records]
        
        # 绘制SV和PV（左侧y轴）
        ax1.plot(sim_times, sv_values, label='SV', color='blue', linewidth=1.5, alpha=0.7)
        ax1.plot(sim_times, pv_values, label='PV', color='cyan', linewidth=1.5, alpha=0.7)
        
        # 绘制MV（右侧y轴）
        ax2.plot(sim_times, mv_values, label='MV', color='orange', linewidth=1.5, alpha=0.7, linestyle='--')
        
        # 设置标签和标题
        ax1.set_xlabel('模拟时间 (秒)', fontsize=12)
        ax1.set_ylabel('SV / PV', fontsize=12, color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        ax1.grid(True, alpha=0.3)
        ax1.set_title('PID控制曲线', fontsize=14, fontweight='bold')
        
        ax2.set_ylabel('MV', fontsize=12, color='orange')
        ax2.tick_params(axis='y', labelcolor='orange')
        
        # 添加图例
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        
        # 刷新画布
        canvas.draw()

