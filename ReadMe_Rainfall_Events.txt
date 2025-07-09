### Parquet 数据集说明：降雨事件属性集
=============================

1. **文件命名规则**
   - 降雨事件数据集文件: `rain_events_all_stations.parquet`
   - 辅助CSV文件: `rain_events_all_stations.csv`

2. **文件格式**
   - 格式类型: Parquet (列式存储格式)
   - 压缩算法: SNAPPY (默认)
   - 文件大小:
     - 约 50-200 MB (取决于时间跨度和事件数量)
     - CSV文件大小约为Parquet文件的2-3倍

3. **数据内容**
| 列名                  | 描述                          | 单位         | 数据类型   | 属性说明                  |
|-----------------------|-------------------------------|--------------|------------|---------------------------|
| Station               | 站点名称                      | 无           | string     | 原始ERA5数据中的站点标识    |
| Start_Time            | 降雨事件开始时间              | UTC时间      | timestamp  | 精确到小时                |
| End_Time              | 降雨事件结束时间              | UTC时间      | timestamp  | 精确到小时                |
| Duration_hours        | 事件持续时间                  | 小时         | float32    | 包含首尾小时              |
| Total_Rain_mm         | 事件总降雨量                  | 毫米(mm)     | float32    | 累计降水量                |
| Avg_Intensity_mmh     | 平均小时降雨强度              | 毫米/小时    | float32    | 总降雨量/持续时间         |
| Max_Intensity_mmh     | 最大小时降雨强度              | 毫米/小时    | float32    | 事件中单小时最大降雨      |
| Rainy_Hours           | 有效降雨小时数                | 小时         | int32      | >0.1mm的小时数           |
| Intensity_Class       | 降水强度等级                  | 无           | string     | 小雨/中雨/大雨/暴雨/大暴雨/特大暴雨 |
| Year                  | 数据年份                      | 年           | int32      | 便于按年分析              |

4. **数据处理说明**
   - **数据源**: ECMWF ERA5-Land 小时降水数据
   - **处理流程**:
     1. 原始数据转换: 降水单位 m → mm (×1000)
     2. 缺失值处理: -9999.0 → 0 mm
     3. 降雨事件检测:
        - 有效降雨阈值: 0.1 mm
        - 最小无雨间隔: 1小时
     4. 事件属性计算:
        - 开始/结束时间、持续时间、总降雨量
        - 平均强度、最大强度、有效降雨小时数
     5. 强度等级分类:
        - 不足12小时: 按最大小时强度×24换算24小时总量
        - 12小时以上: 直接使用事件总降雨量
        - 分类标准: 国家气象局24小时降水等级标准
   - **时间处理**:
        * 时间信息从文件名解析 (ERA5_YYYYMMDD_HH00.nc)
        * 时间范围: 2015年1月1日至今 (根据输入数据确定)

5. **数据来源**
   - **基础数据**:
        * ECMWF ERA5-Land 再分析数据
        * 分辨率: 0.1°×0.1° (约9公里)
        * 原始获取: Google Earth Engine API
   - **处理平台**:
        * Python 3.10+
        * 主要库: pandas, xarray, pyarrow
   - **生成工具**:
        * `rain_event_detection.py` (自定义降雨事件检测脚本)

6. **使用注意事项**
   - **数据范围**:
        * 包含2014个站点的降雨事件
        * 仅包含检测到的有效降雨事件 (总降雨量>0.1mm)
   - **时间特性**:
        * 跨年降雨事件会被分割
        * 时间精度为小时级
   - **分析建议**:
        * 优先使用Parquet格式进行大数据分析
        * CSV格式适合小规模数据查看
        * 使用pandas读取:
          ```python
          import pandas as pd
          df = pd.read_parquet("rain_events_all_stations.parquet")
          ```
   - **参数调整**:
        * 可通过修改脚本中的`RAIN_THRESHOLD`和`DRY_HOURS`优化事件检测
   - **数据更新**:
        * 添加新年份数据需重新运行处理脚本

---

### Parquet Dataset Documentation: Rainfall Event Properties
============================================================

1. **File Naming Convention**
   - Main dataset: `rain_events_all_stations.parquet`
   - CSV copy: `rain_events_all_stations.csv`

2. **File Format**
   - Format Type: Parquet (Columnar storage)
   - Compression: SNAPPY (default)
   - File Size:
     - ~50-200 MB (depends on time span and event count)
     - CSV size: 2-3x larger than Parquet

3. **Data Content**
| Column               | Description                   | Units        | Data Type  | Attributes               |
|----------------------|-------------------------------|--------------|------------|--------------------------|
| Station              | Station name                  | None         | string     | Original station ID      |
| Start_Time           | Event start time              | UTC          | timestamp  | Hourly precision         |
| End_Time             | Event end time                | UTC          | timestamp  | Hourly precision         |
| Duration_hours       | Event duration                | hours        | float32    | Inclusive of endpoints   |
| Total_Rain_mm        | Total rainfall                | mm           | float32    | Cumulative precipitation |
| Avg_Intensity_mmh    | Average hourly intensity      | mm/h         | float32    | Total/Duration           |
| Max_Intensity_mmh    | Max hourly intensity         | mm/h         | float32    | Peak hour in event       |
| Rainy_Hours          | Effective rainy hours         | hours        | int32      | Hours >0.1mm            |
| Intensity_Class      | Precipitation intensity class | None         | string     | Light/Moderate/Heavy etc.|
| Year                 | Data year                     | year         | int32      | For annual analysis      |

4. **Data Processing Notes**
   - **Source Data**: ECMWF ERA5-Land hourly precipitation
   - **Processing Pipeline**:
     1. Unit conversion: m → mm (×1000)
     2. Missing value: -9999.0 → 0 mm
     3. Event detection:
        - Rain threshold: 0.1 mm
        - Minimum dry period: 1 hour
     4. Attribute calculation:
        - Start/End time, Duration, Total rainfall
        - Avg intensity, Max intensity, Rainy hours
     5. Intensity classification:
        - <12h: Convert max intensity to 24h equivalent
        - ≥12h: Use total rainfall directly
        - Standard: National Meteorological 24h scale
   - **Time Handling**:
        * Extracted from filenames (ERA5_YYYYMMDD_HH00.nc)
        * Time coverage: Jan 1, 2015 - present (input-dependent)

5. **Data Source**
   - **Base Data**:
        * ECMWF ERA5-Land reanalysis
        * Resolution: 0.1°×0.1° (~9km)
        * Original access: Google Earth Engine API
   - **Processing Platform**:
        * Python 3.10+
        * Core libraries: pandas, xarray, pyarrow
   - **Generation Tool**:
        * `rain_event_detection.py` (custom rainfall event detector)

6. **Usage Notes**
   - **Data Scope**:
        * Rainfall events for 2014 stations
        * Only valid events (Total_Rain_mm > 0.1mm) included
   - **Temporal Characteristics**:
        * Cross-year events are split
        * Hourly time precision
   - **Analysis Recommendations**:
        * Prefer Parquet for big data processing
        * Use CSV for small-scale inspection
        * Read with pandas:
          ```python
          import pandas as pd
          df = pd.read_parquet("rain_events_all_stations.parquet")
          ```
   - **Parameter Tuning**:
        * Adjust `RAIN_THRESHOLD` and `DRY_HOURS` in script for event sensitivity
   - **Data Updates**:
        * Reprocess when adding new year data