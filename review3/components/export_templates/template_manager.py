"""
导出模板管理器

负责加载和管理导出模板配置。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

from components.utils.logger import get_logger


logger = get_logger()

# 模板配置目录（相对于模块目录）
TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

# 默认描述（用于双行标题的第二行）
DEFAULT_TIME_DESCRIPTION = "时间戳"
DEFAULT_PARAM_DESCRIPTION = "某工业数据"
DEFAULT_FILE_FORMAT = "csv"
DEFAULT_SHEET_NAME = "控制器"


@dataclass
class ExportTemplate:
    """
    导出模板配置
    
    Attributes:
        name: 模板名称（文件名）
        header_rows: 标题行数（1 或 2）
        title_names: 时间列标题；header_rows=2 时为 "第一行,第二行"
        time_format: 时间格式字符串（strftime）
        file_format: 默认文件格式（csv/xlsx/xls）
        sheet_name: 默认工作表名（Excel）
        uppercase_column_names: 导出位号名是否转大写
    """

    name: str
    header_rows: int = 1
    title_names: str = "timeStamp"
    time_format: str = "%Y/%m/%d %H:%M:%S"
    file_format: str = DEFAULT_FILE_FORMAT
    sheet_name: str = DEFAULT_SHEET_NAME
    uppercase_column_names: bool = True

    def __post_init__(self) -> None:
        """验证配置有效性"""
        if self.header_rows not in [1, 2]:
            raise ValueError(f"header_rows must be 1 or 2, got {self.header_rows}")
        fmt = (self.file_format or "").lower()
        if fmt not in {"csv", "xlsx", "xls"}:
            raise ValueError(f"file_format must be csv/xlsx/xls, got {self.file_format}")
        self.file_format = fmt

    @property
    def time_column_name(self) -> str:
        """兼容导出器：解析时间列第一行表头。"""
        text = (self.title_names or "").strip()
        if self.header_rows == 1:
            return text or "timeStamp"
        if "," in text:
            first, _ = text.split(",", 1)
            return first.strip() or "timeStamp"
        return text or "timeStamp"

    @property
    def time_row2_description(self) -> Optional[str]:
        """兼容导出器：仅双行表头时返回第二行说明。"""
        if self.header_rows != 2:
            return None
        text = (self.title_names or "").strip()
        if "," in text:
            _, rest = text.split(",", 1)
            return rest.strip() or DEFAULT_TIME_DESCRIPTION
        return DEFAULT_TIME_DESCRIPTION

    def to_export_format_defaults(self) -> Dict[str, object]:
        """返回与前端导出对话框字段完全一致的默认值。"""
        return {
            "header_rows": self.header_rows,
            "title_names": self.title_names,
            "time_format": self.time_format,
            "file_format": self.file_format,
            "sheet_name": self.sheet_name,
        }


class TemplateManager:
    """
    模板管理器
    
    负责加载和管理导出模板配置。
    """
    
    def __init__(self, templates_dir: Optional[pathlib.Path] = None) -> None:
        """
        初始化模板管理器
        
        Args:
            templates_dir: 模板配置目录，如果为 None 则使用默认目录
        """
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self._templates: Dict[str, ExportTemplate] = {}
        
        # 确保模板目录存在
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("TemplateManager initialized: templates_dir=%s", self.templates_dir)
    
    def load_template(self, name: str) -> ExportTemplate:
        """
        加载模板配置
        
        Args:
            name: 模板名称（如 prediction, pid_loop_tuning）
            
        Returns:
            导出模板配置对象
            
        Raises:
            FileNotFoundError: 如果模板文件不存在
            ValueError: 如果模板配置格式错误
        """
        # 如果已加载，直接返回
        if name in self._templates:
            return self._templates[name]
        
        # 加载模板文件
        template_path = self.templates_dir / f"{name}.yaml"
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        
        try:
            with template_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            # 解析模板配置
            template = self._parse_template(name, data)
            
            # 缓存模板
            self._templates[name] = template
            
            logger.info("模板加载成功: name=%s, header_rows=%d", name, template.header_rows)
            return template
            
        except Exception as e:
            logger.error("加载模板失败: name=%s, error=%s", name, e, exc_info=True)
            raise ValueError(f"加载模板失败: {name}, 错误: {e}") from e
    
    def _parse_template(self, name: str, data: Dict) -> ExportTemplate:
        """
        解析模板配置数据
        
        Args:
            name: 模板名称
            data: YAML 解析后的字典
            
        Returns:
            导出模板配置对象
        """
        defaults = data.get("defaults")
        if not isinstance(defaults, dict):
            raise ValueError("模板 YAML 必须包含 defaults 对象")

        header_rows = int(defaults.get("header_rows", 1))
        title_names = str(defaults.get("title_names", "timeStamp"))
        time_format = str(defaults.get("time_format", "%Y/%m/%d %H:%M:%S"))
        file_format = str(defaults.get("file_format", DEFAULT_FILE_FORMAT))
        sheet_name = str(defaults.get("sheet_name", DEFAULT_SHEET_NAME))
        uppercase_column_names = bool(defaults.get("uppercase_column_names", True))

        return ExportTemplate(
            name=name,
            header_rows=header_rows,
            title_names=title_names,
            time_format=time_format,
            file_format=file_format,
            sheet_name=sheet_name,
            uppercase_column_names=uppercase_column_names,
        )
    
    def list_templates(self) -> List[str]:
        """
        列出所有可用的模板名称
        
        Returns:
            模板名称列表
        """
        if not self.templates_dir.exists():
            return []
        
        templates = []
        for file_path in self.templates_dir.glob("*.yaml"):
            template_name = file_path.stem
            templates.append(template_name)
        
        return sorted(templates)
    
    def template_exists(self, name: str) -> bool:
        """
        检查模板是否存在
        
        Args:
            name: 模板名称
            
        Returns:
            如果模板存在返回 True，否则返回 False
        """
        template_path = self.templates_dir / f"{name}.yaml"
        return template_path.exists()

