"""
数据导出处理模块
负责各种格式的数据导出
"""
import os
import csv
from datetime import datetime, timedelta
from typing import Dict, Any, List
from PyQt6.QtWidgets import QLineEdit, QFileDialog, QMessageBox, QWidget

# 导入openpyxl用于Excel文件操作
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from .constants import Constants
from .param_handler import ParamHandler
from utils.logger import get_logger

logger = get_logger()


class ExportHandler:
    """数据导出处理器"""
    
    @staticmethod
    def sample_records_per_second(data_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        每秒采样一个数据
        
        Args:
            data_records: 原始数据记录列表
        
        Returns:
            采样后的数据记录列表
        """
        sampled_records = []
        last_sampled_time = -1.0
        
        for record in data_records:
            sim_time = record.get('sim_time', 0)
            # 如果当前时间与上次采样时间相差>=1秒，则采样
            if sim_time - last_sampled_time >= 1.0:
                sampled_records.append(record)
                last_sampled_time = sim_time
        
        # 如果没有采样到数据，至少采样第一个和最后一个
        if not sampled_records:
            sampled_records = [data_records[0]]
            if len(data_records) > 1:
                sampled_records.append(data_records[-1])
        
        return sampled_records
    
    @staticmethod
    def validate_file_path(filename: str, parent: QWidget = None) -> str:
        """
        验证并处理文件路径
        
        Args:
            filename: 文件路径
            parent: 父窗口（用于显示错误消息）
        
        Returns:
            处理后的绝对路径，如果失败返回None
        """
        if not filename:
            return None
        
        # 验证文件路径安全性
        if not os.path.isabs(filename):
            # 处理相对路径，转换为绝对路径
            filename = os.path.abspath(filename)
        
        # 检查目录是否存在，是否有写权限
        dir_path = os.path.dirname(filename)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                if parent:
                    QMessageBox.critical(parent, "错误", f"无法创建目录: {dir_path}\n{str(e)}")
                return None
        
        return filename
    
    @staticmethod
    def export_prediction_template(parent: QWidget, data_records: List[Dict[str, Any]],
                                   time_stretch_input: QLineEdit, instance_name_input: QLineEdit):
        """
        导出预测模板（CSV格式）
        
        格式要求：
        - 第一行：timeStamp PID.mv PID.sv PID.pv PID.Kp PID.Td PID.Ti
        - 第二行：时间戳 PID控制输出 PID预设值 PID输入值 比例系数 积分时间 微分时间
        - 第三行开始：时间戳（格式：2024/5/31 01:58:40） 具体数据值
        - 每秒采样一个数据
        """
        if not data_records:
            QMessageBox.warning(parent, "警告", "没有数据可导出！请先运行模拟。")
            return
        
        # 选择保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"pid_export_{timestamp}.csv"
        
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "导出数据到CSV",
            default_filename,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return
        
        # 验证文件路径
        filename = ExportHandler.validate_file_path(filename, parent)
        if not filename:
            return
        
        try:
            # 获取时间拉伸倍数
            try:
                time_stretch = float(time_stretch_input.text() or "1")
                if time_stretch <= 0:
                    QMessageBox.warning(parent, "警告", "时间拉伸倍数必须大于0！")
                    return
            except ValueError:
                QMessageBox.warning(parent, "警告", "时间拉伸倍数格式错误，请输入数字！")
                return
            
            # 每秒采样一个数据
            sampled_records = ExportHandler.sample_records_per_second(data_records)
            
            # 获取实例名（用于位号前缀）
            instance_name = instance_name_input.text().strip() or "PID_TEST_1"
            
            # 写入CSV文件
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # 第一行：timeStamp {实例名}_pid.MV {实例名}_pid.SV ...（使用新格式）
                writer.writerow([
                    'timeStamp',
                    ParamHandler.format_tag_name(instance_name, 'pid.mv'),
                    ParamHandler.format_tag_name(instance_name, 'pid.sv'),
                    ParamHandler.format_tag_name(instance_name, 'pid.pv'),
                    ParamHandler.format_tag_name(instance_name, 'pid.kp'),
                    ParamHandler.format_tag_name(instance_name, 'pid.pb'),
                    ParamHandler.format_tag_name(instance_name, 'pid.td'),
                    ParamHandler.format_tag_name(instance_name, 'pid.ti'),
                    ParamHandler.format_tag_name(instance_name, 'pid.mode'),
                    ParamHandler.format_tag_name(instance_name, 'pid.cas'),
                    ParamHandler.format_tag_name(instance_name, 'pid.swpn'),
                    ParamHandler.format_tag_name(instance_name, 'pid.svsch'),
                    ParamHandler.format_tag_name(instance_name, 'pid.svh'),
                    ParamHandler.format_tag_name(instance_name, 'pid.svscl'),
                    ParamHandler.format_tag_name(instance_name, 'pid.mvscl'),
                    ParamHandler.format_tag_name(instance_name, 'pid.svl'),
                    ParamHandler.format_tag_name(instance_name, 'pid.mvl'),
                    ParamHandler.format_tag_name(instance_name, 'pid.mvsch'),
                    ParamHandler.format_tag_name(instance_name, 'pid.mvh'),
                    ParamHandler.format_tag_name(instance_name, 'tank.level'),
                    ParamHandler.format_tag_name(instance_name, 'valve.current_opening')
                ])
                
                # 第二行：中文描述，对应各位号含义
                writer.writerow([
                    '时间戳',
                    'PID控制输出',
                    'PID预设值',
                    'PID输入值',
                    '比例系数',
                    '比例带',
                    '微分时间',
                    '积分时间',
                    'PID模式',
                    '级联标志',
                    'PID开关逻辑',
                    'SV上量程',
                    'SV工程上限',
                    'SV工程下限',
                    'MV工程下限',
                    'SV显示下限',
                    'MV显示下限',
                    'MV上量程',
                    'MV工程上限',
                    '水箱液位',
                    '阀门开度'
                ])
                
                # 第三行开始：时间戳（格式：2024/5/31 01:58:40） 具体数据值
                base_time = Constants.DEFAULT_BASE_TIME
                
                for record in sampled_records:
                    sim_time = record.get('sim_time', 0)
                    # 计算时间戳：基准时间 + sim_time * time_stretch秒数（应用时间拉伸）
                    stretched_time = sim_time * time_stretch
                    record_time = base_time + timedelta(seconds=stretched_time)
                    
                    # 格式：2024/5/31 01:58:40（注意：月份和日期不补零，小时分钟秒补零）
                    time_str = f"{record_time.year}/{record_time.month}/{record_time.day} {record_time.hour:02d}:{record_time.minute:02d}:{record_time.second:02d}"
                    
                    # 获取数据值（包含所有扩展后的PID相关位号与过程量）
                    pid_mv = record.get('pid.mv', 0)
                    pid_sv = record.get('pid.sv', 0)
                    pid_pv = record.get('pid.pv', 0)
                    pid_kp = record.get('pid.kp', 0)
                    pid_pb = record.get('pid.pb', 0)
                    pid_td = record.get('pid.td', 0)
                    pid_ti = record.get('pid.ti', 0)
                    pid_mode = record.get('pid.mode', 20)
                    pid_cas = record.get('pid.cas', 0)
                    pid_swpn = record.get('pid.swpn', 1)
                    pid_svsch = record.get('pid.svsch', 0)
                    pid_svh = record.get('pid.svh', 0)
                    pid_svscl = record.get('pid.svscl', 0)
                    pid_mvscl = record.get('pid.mvscl', 0)
                    pid_svl = record.get('pid.svl', 0)
                    pid_mvl = record.get('pid.mvl', 0)
                    pid_mvsch = record.get('pid.mvsch', 100)
                    pid_mvh = record.get('pid.mvh', 100)
                    tank_level = record.get('tank.level', 0)
                    valve_opening = record.get('valve.current_opening', 0)
                    
                    writer.writerow([
                        time_str,
                        ParamHandler.format_float(pid_mv),
                        ParamHandler.format_float(pid_sv),
                        ParamHandler.format_float(pid_pv),
                        ParamHandler.format_float(pid_kp),
                        ParamHandler.format_float(pid_pb),
                        ParamHandler.format_float(pid_td),
                        ParamHandler.format_float(pid_ti),
                        ParamHandler.format_float(pid_mode),
                        ParamHandler.format_float(pid_cas),
                        ParamHandler.format_float(pid_swpn),
                        ParamHandler.format_float(pid_svsch),
                        ParamHandler.format_float(pid_svh),
                        ParamHandler.format_float(pid_svscl),
                        ParamHandler.format_float(pid_mvscl),
                        ParamHandler.format_float(pid_svl),
                        ParamHandler.format_float(pid_mvl),
                        ParamHandler.format_float(pid_mvsch),
                        ParamHandler.format_float(pid_mvh),
                        ParamHandler.format_float(tank_level),
                        ParamHandler.format_float(valve_opening)
                    ])
            
            # 计算原始时间跨度和拉伸后的时间跨度
            if sampled_records:
                original_duration = sampled_records[-1].get('sim_time', 0) - sampled_records[0].get('sim_time', 0)
                stretched_duration = original_duration * time_stretch
            else:
                original_duration = 0
                stretched_duration = 0
            
            stretch_info = f"，时间拉伸倍数：{time_stretch}" if time_stretch != 1 else ""
            QMessageBox.information(
                parent, 
                "导出成功", 
                f"数据已成功导出到：\n{filename}\n\n"
                f"共导出 {len(sampled_records)} 条记录（每秒1条）{stretch_info}。\n"
                f"原始时间跨度：{original_duration:.1f}秒，拉伸后时间跨度：{stretched_duration:.1f}秒。"
            )
            
        except FileNotFoundError as e:
            QMessageBox.critical(parent, "导出失败", f"文件未找到：\n{str(e)}")
        except PermissionError as e:
            QMessageBox.critical(parent, "导出失败", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(parent, "导出失败", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(parent, "导出失败", f"导出数据时发生错误：\n{str(e)}")
            logger.exception("Error exporting data to CSV")
    
    @staticmethod
    def export_pid_tuning_template(parent: QWidget, data_records: List[Dict[str, Any]],
                                   time_stretch_input: QLineEdit, instance_name_input: QLineEdit):
        """
        导出PID整定模板（CSV格式）
        
        格式要求：
        - 第一行：时间 PV MV SV三个格式化后的位号名
        - 第二行开始：数据行，时间格式为 yyyy-MM-dd HH:mm:ss
        - 只导出PV、MV、SV三个位号
        """
        if not data_records:
            QMessageBox.warning(parent, "警告", "没有数据可导出！请先运行模拟。")
            return
        
        # 选择保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"pid_tuning_export_{timestamp}.csv"
        
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "导出PID整定模板",
            default_filename,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return
        
        # 验证文件路径
        filename = ExportHandler.validate_file_path(filename, parent)
        if not filename:
            return
        
        try:
            # 获取时间拉伸倍数
            try:
                time_stretch = float(time_stretch_input.text() or "1")
                if time_stretch <= 0:
                    QMessageBox.warning(parent, "警告", "时间拉伸倍数必须大于0！")
                    return
            except ValueError:
                QMessageBox.warning(parent, "警告", "时间拉伸倍数格式错误，请输入数字！")
                return
            
            # 获取实例名
            instance_name = instance_name_input.text().strip() or "PID_TEST_1"
            
            # 每秒采样一个数据（与预测模板共用采样逻辑）
            sampled_records = ExportHandler.sample_records_per_second(data_records)
            
            # 写入CSV文件
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # 第一行：时间 PV MV SV（使用格式化后的位号名）
                writer.writerow([
                    '时间',
                    ParamHandler.format_tag_name(instance_name, 'pid.pv'),
                    ParamHandler.format_tag_name(instance_name, 'pid.mv'),
                    ParamHandler.format_tag_name(instance_name, 'pid.sv')
                ])
                
                # 第二行开始：数据行，时间格式为 yyyy-MM-dd HH:mm:ss
                base_time = Constants.DEFAULT_BASE_TIME
                
                for record in sampled_records:
                    sim_time = record.get('sim_time', 0)
                    # 计算时间戳：基准时间 + sim_time * time_stretch秒数（应用时间拉伸）
                    stretched_time = sim_time * time_stretch
                    record_time = base_time + timedelta(seconds=stretched_time)
                    
                    # 格式：yyyy-MM-dd HH:mm:ss
                    time_str = record_time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 获取数据值（只导出PV、MV、SV）
                    pid_pv = record.get('pid.pv', 0)
                    pid_mv = record.get('pid.mv', 0)
                    pid_sv = record.get('pid.sv', 0)
                    
                    writer.writerow([
                        time_str,
                        ParamHandler.format_float(pid_pv),
                        ParamHandler.format_float(pid_mv),
                        ParamHandler.format_float(pid_sv)
                    ])
            
            # 计算原始时间跨度和拉伸后的时间跨度
            if sampled_records:
                original_duration = sampled_records[-1].get('sim_time', 0) - sampled_records[0].get('sim_time', 0)
                stretched_duration = original_duration * time_stretch
            else:
                original_duration = 0
                stretched_duration = 0
            
            stretch_info = f"，时间拉伸倍数：{time_stretch}" if time_stretch != 1 else ""
            QMessageBox.information(
                parent,
                "导出成功",
                f"PID整定模板已成功导出到：\n{filename}\n\n"
                f"共导出 {len(sampled_records)} 条记录（每秒1条）{stretch_info}。\n"
                f"原始时间跨度：{original_duration:.1f}秒，拉伸后时间跨度：{stretched_duration:.1f}秒。"
            )
            
        except FileNotFoundError as e:
            QMessageBox.critical(parent, "导出失败", f"文件未找到：\n{str(e)}")
        except PermissionError as e:
            QMessageBox.critical(parent, "导出失败", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(parent, "导出失败", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(parent, "导出失败", f"导出数据时发生错误：\n{str(e)}")
            logger.exception("Error exporting PID tuning template")
    
    @staticmethod
    def export_tpt_template(parent: QWidget, instance_name_input: QLineEdit, tpt_datasource_input: QLineEdit):
        """
        导出TPT导入位号模板（Excel格式）
        
        格式要求：
        - 1个sheet页，名字是sheet1
        - 系统位号名和描述：完整位号名（实例名.参数名）
        - 底层位号名：1_{完整位号名}（namespace=1）
        - 数据源名称：从界面配置
        - 数据类型：DOUBLE
        - 采集频率：1
        - 缓存数量：100
        - 是否向量位号：TRUE
        - 节点名：根节点
        """
        if not OPENPYXL_AVAILABLE:
            QMessageBox.critical(
                parent, 
                "错误", 
                "未安装openpyxl库，无法导出Excel文件！\n\n"
                "请运行以下命令安装：\n"
                "pip install openpyxl"
            )
            return
        
        # 获取数据源名称
        datasource_name = tpt_datasource_input.text().strip()
        if not datasource_name:
            QMessageBox.warning(parent, "警告", "请输入数据源名称！")
            return
        
        # 获取实例名
        instance_name = instance_name_input.text().strip() or "PID_TEST_1"
        
        # 选择保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"tpt_tag_template_{timestamp}.xlsx"
        
        filename, _ = QFileDialog.getSaveFileName(
            parent,
            "导出TPT导入位号模板",
            default_filename,
            "Excel Files (*.xlsx);;All Files (*)"
        )
        
        if not filename:
            return
        
        # 验证文件路径
        filename = ExportHandler.validate_file_path(filename, parent)
        if not filename:
            return
        
        try:
            # 创建Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "sheet1"
            
            # 定义所有位号（8个位号）- 使用常量定义
            tag_names = Constants.TAG_DEFINITIONS
            
            # 写入表头
            headers = [
                '系统位号名', '底层位号名', '位号类型', '数据源名称（一次位号）', '单位',
                '数据类型', '取值表达式（二次位号）', '位号值（虚位号）', '采集频率',
                '缓存数量', '是否为向量位号', '位号值高限', '位号值高二限', '位号值高三限',
                '位号值低限', '位号值低二限', '位号值低三限', '描述', '节点名'
            ]
            ws.append(headers)
            
            # 设置表头样式
            header_font = Font(bold=True)
            for cell in ws[1]:
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # 写入数据行
            namespace = 1  # OPCUA命名空间索引
            for tag_key, tag_desc in tag_names:
                # 使用新格式：{实例名}_{param_prefix}.{param_suffix.UPPER}
                full_tag_name = ParamHandler.format_tag_name(instance_name, tag_key)
                bottom_tag_name = f"{namespace}_{full_tag_name}"  # 底层位号名：1_{完整位号名}
                
                row_data = [
                    full_tag_name,  # 系统位号名
                    bottom_tag_name,  # 底层位号名
                    '一次位号',  # 位号类型
                    datasource_name,  # 数据源名称（一次位号）
                    '',  # 单位
                    'DOUBLE',  # 数据类型
                    '',  # 取值表达式（二次位号）
                    '',  # 位号值（虚位号）
                    1,  # 采集频率
                    100,  # 缓存数量
                    'TRUE',  # 是否为向量位号
                    '',  # 位号值高限
                    '',  # 位号值高二限
                    '',  # 位号值高三限
                    '',  # 位号值低限
                    '',  # 位号值低二限
                    '',  # 位号值低三限
                    full_tag_name,  # 描述（与系统位号名一致）
                    '根节点'  # 节点名
                ]
                ws.append(row_data)
            
            # 调整列宽（可选）
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # 保存文件
            wb.save(filename)
            
            QMessageBox.information(
                parent,
                "导出成功",
                f"TPT导入位号模板已成功导出到：\n{filename}\n\n"
                f"共导出 {len(tag_names)} 个位号。\n"
                f"数据源名称：{datasource_name}\n"
                f"实例名：{instance_name}"
            )
            
        except PermissionError as e:
            QMessageBox.critical(parent, "导出失败", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(parent, "导出失败", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(parent, "导出失败", f"导出TPT模板时发生错误：\n{str(e)}")
            logger.exception("Error exporting TPT template")

