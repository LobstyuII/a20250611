MERRA-2 臭氧与总可降水量数据文件说明
===============================

1. 文件命名规则
   - 格式: MERRA2_YYYYMMDD_HHMM_TO3_TQV.nc
     示例: MERRA2_20150801_0200_TO3_TQV.nc
   - 说明:
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * MM: 分钟 (小时数据固定为00)
     * TO3_TQV: 表示包含臭氧柱与总可降水量数据

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度: 2 (时间维度+站点维度)
   - 变量: 6个
   - 文件大小: 约150-200 KB

3. 数据内容
   | 变量名    | 描述                     | 单位          | 数据类型 | 维度             |
   |-----------|--------------------------|---------------|----------|------------------|
   | Station   | 站点名称                 | 无            | 字符串   | Station(N)      |
   | Lat       | 纬度坐标                 | 度            | float32  | Station(N)      |
   | Lon       | 经度坐标                 | 度            | float32  | Station(N)      |
   | TO3       | 总柱状臭氧浓度           | Dobson        | float32  | Station(N)      |
   | TQV       | 总可降水量（水汽柱总量） | kg/m²         | float32  | Station(N)      |

4. 数据处理说明
   - 数据来源: NASA MERRA-2再分析数据集
   - 时间分辨率: 小时级(1小时)
   - 空间分辨率: 约50km
   - 数据质量:
     * TO3有效值范围: 100-600 Dobson (典型值)
     * TQV有效值范围: 0-100 kg/m² (典型值)
     * 缺失值: -9999.0
     * 全球覆盖完整性: 100%
   - 时间表示:
     * 文件命名时间: UTC小时时间(HH00)
     * 内部时间变量: hours since 1980-01-01 00:00:00
     * 完整时间戳: YYYY-MM-DD HH:00 UTC

5. 数据来源
   - 项目: NASA现代回顾性分析研究及应用-2版(MERRA-2)
   - 产品: M2T1NXSLV: 单层诊断 V5.12.4
   - 分辨率: 时间: 1小时, 空间: 0.5°×0.625°
   - 获取方式: Google Earth Engine
     ee.ImageCollection("NASA/GSFC/MERRA/slv/2")

6. 使用注意事项
   - 文件包含特定站点的臭氧柱与水汽柱总量数据
   - 每个文件代表单个整点时间(小时数据)
   - 最终合并数据存储在MERRA2_TO3_TQV_combined.nc
   - 处理脚本使用GEE API并行下载，含错误重试机制
   - 数据适用于大气化学、水循环及气候研究


----------------------------------------------------------------

MERRA-2 Ozone and Total Precipitable Water Data File Documentation
=====================================================================

1. File Naming Convention
   - Format: MERRA2_YYYYMMDD_HHMM_TO3_TQV.nc
     Example: MERRA2_20150801_0200_TO3_TQV.nc
   - Description:
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * MM: Minute (fixed as 00 for hourly data)
     * TO3_TQV: Indicates inclusion of ozone and water vapor data

2. File Format
   - Format Type: NetCDF-4
   - Dimensions: 2 (Time + Station)
   - Variables: 6
   - File Size: ~150-200 KB

3. Data Content
   | Variable  | Description                   | Unit        | Data Type | Dimension       |
   |-----------|-------------------------------|-------------|-----------|-----------------|
   | Station   | Station names                 | None        | String    | Station(N)     |
   | Lat       | Latitude coordinates          | degrees     | float32   | Station(N)     |
   | Lon       | Longitude coordinates         | degrees     | float32   | Station(N)     |
   | TO3       | Total Column Ozone            | Dobson      | float32   | Station(N)      |
   | TQV       | Total Precipitable Water Vapor | kg/m²       | float32   |  Station(N)      |

4. Data Processing Notes
   - Data Source: NASA MERRA-2 reanalysis dataset
   - Temporal Resolution: Hourly (1-hour)
   - Spatial Resolution: ~50km
   - Data Quality:
     * TO3 Valid Range: 100-600 Dobson (typical)
     * TQV Valid Range: 0-100 kg/m² (typical)
     * Missing Values: -9999.0
     * Global Coverage Completeness: 100%
   - Time Representation:
     * Filename Time: UTC hour (HH00)
     * Internal Time Variable: hours since 1980-01-01 00:00:00
     * Full Timestamp: YYYY-MM-DD HH:00 UTC

5. Data Source
   - Project: NASA Modern-Era Retrospective analysis for Research and Applications-2
   - Product: M2T1NXSLV: Single-Level Diagnostics V5.12.4
   - Resolution: Time: 1-hour, Space: 0.5°×0.625°
   - Access: Google Earth Engine
     ee.ImageCollection("NASA/GSFC/MERRA/slv/2")

6. Usage Notes
   - Contains total column ozone and water vapor data for specific stations
   - Each file represents a single hourly timepoint
   - Final integrated data stored in MERRA2_TO3_TQV_combined.nc
   - Processing script uses GEE API with parallel download and error retry
   - Suitable for atmospheric chemistry, hydrological cycle, and climate studies