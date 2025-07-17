# MERRA-2 气溶胶光学厚度（AOT550）数据文件说明
===============================

## 1. 文件命名规则
- **格式**: `MERRA2_YYYYMMDD_HHMM_AOT550.nc`
  示例: `MERRA2_20150801_0200_AOT550.nc`
- **说明**:
  - `YYYY`: 年份 (4位数字)
  - `MM`: 月份 (2位数字)
  - `DD`: 日期 (2位数字)
  - `HH`: 小时 (UTC时间，2位数字)
  - `MM`: 分钟 (小时数据固定为00)
  - `AOT550`: 表示包含550nm气溶胶光学厚度数据

## 2. 文件格式
- **格式类型**: NetCDF-4
- **维度**: 1 (站点维度)
- **变量**: 5个
- **文件大小**: 约100-150 KB

## 3. 数据内容
| 变量名    | 描述                     | 单位          | 数据类型 | 维度             |
|-----------|--------------------------|---------------|----------|------------------|
| Station   | 站点名称                 | 无            | 字符串   | Station(N)      |
| Lat       | 纬度坐标                 | 度            | float32  | Station(N)      |
| Lon       | 经度坐标                 | 度            | float32  | Station(N)      |
| AOT550    | 550nm气溶胶光学厚度      | 1             | float32  | Station(N)      |

## 4. 数据处理说明
- **数据来源**: NASA MERRA-2再分析数据集
- **时间分辨率**: 小时级(1小时)
- **空间分辨率**: 约50km
- **数据质量**:
  - AOT550有效值范围: 0-5 (典型值)
  - 缺失值: -9999.0
  - 全球覆盖完整性: 100%
- **时间表示**:
  - 文件命名时间: UTC小时时间(HH00)
  - 文件属性时间: ISO格式时间戳 (YYYY-MM-DDTHH:MM:SS)
  - 完整时间戳: YYYY-MM-DD HH:00 UTC

## 5. 数据来源
- **项目**: NASA现代回顾性分析研究及应用-2版(MERRA-2)
- **产品**: M2T1NXAER: 气溶胶诊断 V5.12.4
- **分辨率**:
  - 时间: 1小时
  - 空间: 0.5°×0.625°
- **获取方式**: Google Earth Engine
  `ee.ImageCollection("NASA/GSFC/MERRA/aer/2")`
- **原始变量**: TOTEXTTAU (总消光气溶胶光学厚度)

## 6. 使用注意事项
- 文件包含特定站点的550nm气溶胶光学厚度数据
- 每个文件代表单个整点时间(小时数据)
- 最终合并数据存储在`MERRA2_AOT550_combined.nc`
- 处理脚本使用GEE API并行下载，含错误重试机制
- 数据适用于大气气溶胶、空气质量及气候研究
- 典型应用场景:
  - 气溶胶传输模型验证
  - 空气质量监测与预测
  - 气溶胶-云相互作用研究
  - 太阳辐射传输计算

---

# MERRA-2 Aerosol Optical Depth (AOT550) Data File Documentation
=====================================================================

## 1. File Naming Convention
- **Format**: `MERRA2_YYYYMMDD_HHMM_AOT550.nc`
  Example: `MERRA2_20150801_0200_AOT550.nc`
- **Description**:
  - `YYYY`: Year (4-digit)
  - `MM`: Month (2-digit)
  - `DD`: Day (2-digit)
  - `HH`: Hour (UTC, 2-digit)
  - `MM`: Minute (fixed as 00 for hourly data)
  - `AOT550`: Indicates aerosol optical depth at 550nm data

## 2. File Format
- **Format Type**: NetCDF-4
- **Dimensions**: 1 (Station)
- **Variables**: 5
- **File Size**: ~100-150 KB

## 3. Data Content
| Variable  | Description                   | Unit        | Data Type | Dimension       |
|-----------|-------------------------------|-------------|-----------|-----------------|
| Station   | Station names                 | None        | String    | Station(N)     |
| Lat       | Latitude coordinates          | degrees     | float32   | Station(N)     |
| Lon       | Longitude coordinates         | degrees     | float32   | Station(N)     |
| AOT550    | Aerosol Optical Depth at 550nm| 1           | float32   | Station(N)     |

## 4. Data Processing Notes
- **Data Source**: NASA MERRA-2 reanalysis dataset
- **Temporal Resolution**: Hourly (1-hour)
- **Spatial Resolution**: ~50km
- **Data Quality**:
  - AOT550 Valid Range: 0-5 (typical)
  - Missing Values: -9999.0
  - Global Coverage Completeness: 100%
- **Time Representation**:
  - Filename Time: UTC hour (HH00)
  - File Attribute Time: ISO timestamp (YYYY-MM-DDTHH:MM:SS)
  - Full Timestamp: YYYY-MM-DD HH:00 UTC

## 5. Data Source
- **Project**: NASA Modern-Era Retrospective analysis for Research and Applications-2
- **Product**: MERRA-2 M2T1NXAER: Aerosol Diagnostics V5.12.4
- **Resolution**:
  - Time: 1-hour
  - Space: 0.5°×0.625°
- **Access**: Google Earth Engine
  `ee.ImageCollection("NASA/GSFC/MERRA/aer/2")`
- **Original Variable**: TOTEXTTAU (Total Extinction Aerosol Optical Depth)

## 6. Usage Notes
- Contains aerosol optical depth at 550nm for specific stations
- Each file represents a single hourly timepoint
- Final integrated data stored in `MERRA2_AOT550_combined.nc`
- Processing script uses GEE API with parallel download and error retry
- Suitable for aerosol transport modeling, air quality monitoring, and climate studies
- Typical applications:
  - Validation of aerosol transport models
  - Air quality monitoring and forecasting
  - Aerosol-cloud interaction studies
  - Solar radiation transfer calculations