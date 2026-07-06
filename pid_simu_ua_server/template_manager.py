"""
模板管理模块
负责模板的导入和导出
"""
import os
import json
from datetime import datetime
from typing import Dict, Any
from PyQt6.QtWidgets import QLineEdit, QFileDialog, QMessageBox, QWidget
from utils.logger import get_logger

logger = get_logger()


class TemplateManager:
    """模板管理器"""
    
    @staticmethod
    def collect_template_data(tank_height: QLineEdit, tank_radius: QLineEdit,
                             tank_inlet_area: QLineEdit, tank_inlet_velocity: QLineEdit,
                             tank_outlet_area: QLineEdit, tank_initial_level: QLineEdit,
                             valve_min_opening: QLineEdit, valve_max_opening: QLineEdit,
                             valve_full_travel_time: QLineEdit,
                             pid_kp: QLineEdit, pid_ti: QLineEdit, pid_td: QLineEdit,
                             pid_sv: QLineEdit, pid_pv: QLineEdit, pid_mv: QLineEdit,
                             pid_h: QLineEdit, pid_l: QLineEdit,
                             duration_input: QLineEdit) -> Dict[str, Any]:
        """收集所有参数配置"""
        return {
            'tank': {
                'height': tank_height.text(),
                'radius': tank_radius.text(),
                'inlet_area': tank_inlet_area.text(),
                'inlet_velocity': tank_inlet_velocity.text(),
                'outlet_area': tank_outlet_area.text(),
                'initial_level': tank_initial_level.text()
            },
            'valve': {
                'min_opening': valve_min_opening.text(),
                'max_opening': valve_max_opening.text(),
                'full_travel_time': valve_full_travel_time.text()
            },
            'pid': {
                'kp': pid_kp.text(),
                'ti': pid_ti.text(),
                'td': pid_td.text(),
                'sv': pid_sv.text(),
                'pv': pid_pv.text(),
                'mv': pid_mv.text(),
                'h': pid_h.text(),
                'l': pid_l.text()
            },
            'simulation': {
                'duration': duration_input.text()
            }
        }
    
    @staticmethod
    def export_template(parent: QWidget,
                       tank_height: QLineEdit, tank_radius: QLineEdit,
                       tank_inlet_area: QLineEdit, tank_inlet_velocity: QLineEdit,
                       tank_outlet_area: QLineEdit, tank_initial_level: QLineEdit,
                       valve_min_opening: QLineEdit, valve_max_opening: QLineEdit,
                       valve_full_travel_time: QLineEdit,
                       pid_kp: QLineEdit, pid_ti: QLineEdit, pid_td: QLineEdit,
                       pid_sv: QLineEdit, pid_pv: QLineEdit, pid_mv: QLineEdit,
                       pid_h: QLineEdit, pid_l: QLineEdit,
                       duration_input: QLineEdit):
        """
        导出模板：保存所有参数配置到JSON文件
        """
        try:
            # 收集所有参数配置
            template = TemplateManager.collect_template_data(
                tank_height, tank_radius, tank_inlet_area, tank_inlet_velocity,
                tank_outlet_area, tank_initial_level,
                valve_min_opening, valve_max_opening, valve_full_travel_time,
                pid_kp, pid_ti, pid_td, pid_sv, pid_pv, pid_mv, pid_h, pid_l,
                duration_input
            )
            
            # 选择保存文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"pid_template_{timestamp}.json"
            
            filename, _ = QFileDialog.getSaveFileName(
                parent,
                "导出模板",
                default_filename,
                "JSON Files (*.json);;All Files (*)"
            )
            
            if not filename:
                return
            
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
                    QMessageBox.critical(parent, "错误", f"无法创建目录: {dir_path}\n{str(e)}")
                    return
            
            # 保存到JSON文件
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(template, f, ensure_ascii=False, indent=4)
            
            QMessageBox.information(parent, "成功", f"模板已保存到：\n{filename}")
            
        except PermissionError as e:
            QMessageBox.critical(parent, "错误", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(parent, "错误", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(parent, "错误", f"导出模板失败：\n{str(e)}")
            logger.exception("Error exporting template")
    
    @staticmethod
    def import_template(parent: QWidget,
                       tank_height: QLineEdit, tank_radius: QLineEdit,
                       tank_inlet_area: QLineEdit, tank_inlet_velocity: QLineEdit,
                       tank_outlet_area: QLineEdit, tank_initial_level: QLineEdit,
                       valve_min_opening: QLineEdit, valve_max_opening: QLineEdit,
                       valve_full_travel_time: QLineEdit,
                       pid_kp: QLineEdit, pid_ti: QLineEdit, pid_td: QLineEdit,
                       pid_sv: QLineEdit, pid_pv: QLineEdit, pid_mv: QLineEdit,
                       pid_h: QLineEdit, pid_l: QLineEdit,
                       duration_input: QLineEdit):
        """
        导入模板：从JSON文件加载所有参数配置
        """
        try:
            # 选择文件
            filename, _ = QFileDialog.getOpenFileName(
                parent,
                "导入模板",
                "",
                "JSON Files (*.json);;All Files (*)"
            )
            
            if not filename:
                return
            
            # 验证文件路径安全性
            if not os.path.exists(filename):
                QMessageBox.critical(parent, "错误", f"文件不存在：\n{filename}")
                return
            
            # 读取JSON文件
            with open(filename, 'r', encoding='utf-8') as f:
                template = json.load(f)
            
            # 加载水箱参数
            if 'tank' in template:
                tank = template['tank']
                tank_height.setText(str(tank.get('height', '')))
                tank_radius.setText(str(tank.get('radius', '')))
                tank_inlet_area.setText(str(tank.get('inlet_area', '')))
                tank_inlet_velocity.setText(str(tank.get('inlet_velocity', '')))
                tank_outlet_area.setText(str(tank.get('outlet_area', '')))
                tank_initial_level.setText(str(tank.get('initial_level', '')))
            
            # 加载阀门参数
            if 'valve' in template:
                valve = template['valve']
                valve_min_opening.setText(str(valve.get('min_opening', '')))
                valve_max_opening.setText(str(valve.get('max_opening', '')))
                valve_full_travel_time.setText(str(valve.get('full_travel_time', '')))
            
            # 加载PID参数
            if 'pid' in template:
                pid = template['pid']
                pid_kp.setText(str(pid.get('kp', '')))
                pid_ti.setText(str(pid.get('ti', '')))
                pid_td.setText(str(pid.get('td', '')))
                pid_sv.setText(str(pid.get('sv', '')))
                pid_pv.setText(str(pid.get('pv', '')))
                pid_mv.setText(str(pid.get('mv', '')))
                pid_h.setText(str(pid.get('h', '')))
                pid_l.setText(str(pid.get('l', '')))
            
            # 加载模拟设置
            if 'simulation' in template:
                sim = template['simulation']
                duration_input.setText(str(sim.get('duration', '')))
            
            QMessageBox.information(parent, "成功", f"模板已从以下文件加载：\n{filename}")
            
        except FileNotFoundError as e:
            QMessageBox.critical(parent, "错误", f"文件未找到：\n{str(e)}")
        except PermissionError as e:
            QMessageBox.critical(parent, "错误", f"没有权限访问文件：\n{str(e)}")
        except json.JSONDecodeError as e:
            QMessageBox.critical(parent, "错误", f"JSON文件格式错误：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(parent, "错误", f"导入模板失败：\n{str(e)}")
            logger.exception("Error importing template")

