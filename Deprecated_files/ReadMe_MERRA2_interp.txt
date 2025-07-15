MERRA-2 10分钟分辨率臭氧与总可降水量数据文件说明
============================================

1. 文件命名规则
   - 格式: MERRA2_interp_YYYYMMDD_HHMM_TO3_TQV.nc
     示例: MERRA2_interp_20150801_0210_TO3_TQV.nc
   - 说明:
     * "interp": 表示插值数据
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * MM: 分钟 (10分钟间隔: 00,10,20,...,50)
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
   | time      | 时间参考值               | 小时数        | float64  | time(1)         |
   | TO3       | 总柱状臭氧浓度           | Dobson        | float32  | time(1), Station(N) |
   | TQV       | 总可降水量(水汽柱总量)   | kg/m²         | float32  | time(1), Station(N) |

4. 数据处理说明
   - 原始数据来源: NASA MERRA-2再分析数据集(M2T1NXSLV产品)
   - 时间分辨率:
     * 原始数据: 小时级(1小时)
     * 生成数据: 10分钟级(插值)
   - 空间分辨率: 约50km (保持原始分辨率)
   - 插值方法: 时间维度线性插值
   - 数据质量:
     * TO3有效值范围: 100-600 Dobson
     * TQV有效值范围: 0-100 kg/m²
     * 缺失值: -9999.0 (原始数据缺失或插值失败时)
     * 时间范围: 2015年7月7日 - 2021年12月31日
   - 时间表示:
     * 文件命名时间: UTC精确时间(HHMM)
     * 内部时间变量: hours since 1980-01-01 00:00:00
     * 完整时间戳: YYYY-MM-DD HH:MM UTC

5. 数据处理流程
   - 步骤1: 从原始小时数据文件读取TO3/TQV数据
   - 步骤2: 生成10分钟间隔时间序列(00,10,20,...,50)
   - 步骤3: 整点时刻使用原始数据，非整点时刻执行线性插值
   - 步骤4: 并行写入NetCDF文件(按年/月目录组织)
   - 关键技术:
     * 内存缓存: 最近48小时数据缓存优化
     * 并行处理: 多进程加速(默认4线程)
     * 容错机制: 缺失数据自动填充

6. 使用注意事项
   - 目录结构:
     /年/月/MERRA2_interp_*.nc (示例: /2015/08/)
   - 全球站点覆盖: 包含所有MERRA-2网格点
   - 适用场景:
     * 高时间分辨率大气研究
     * 卫星数据时间匹配
     * 气象模型验证
   - 数据验证: 建议对比原始小时数据检查插值质量
   - 限制: 长时间数据缺失可能导致插值误差增大


----------------------------------------------------------------

MERRA-2 10-min Resolution Ozone and Precipitable Water Data Documentation
=========================================================================

1. File Naming Convention
   - Format: MERRA2_interp_YYYYMMDD_HHMM_TO3_TQV.nc
     Example: MERRA2_interp_20150801_0210_TO3_TQV.nc
   - Description:
     * "interp": Indicates interpolated data
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * MM: Minute (10-min intervals: 00,10,20,...,50)
     * TO3_TQV: Ozone and water vapor data

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
   | time      | Time reference                | hours       | float64   | time(1)        |
   | TO3       | Total Column Ozone            | Dobson      | float32   | time(1), Station(N) |
   | TQV       | Total Precipitable Water Vapor | kg/m²       | float32   | time(1), Station(N) |

4. Data Processing Notes
   - Source: NASA MERRA-2 reanalysis (M2T1NXSLV product)
   - Temporal Resolution:
     * Original: 1-hour
     * Generated: 10-min (interpolated)
   - Spatial Resolution: ~50km (same as source)
   - Interpolation: Linear temporal interpolation
   - Data Quality:
     * TO3 Valid Range: 100-600 Dobson
     * TQV Valid Range: 0-100 kg/m²
     * Missing Value: -9999.0 (source missing or interpolation failure)
     * Coverage: 2015-07-07 to 2021-12-31
   - Time Representation:
     * Filename: Exact UTC time (HHMM)
     * Time Variable: hours since 1980-01-01 00:00:00
     * Full Timestamp: YYYY-MM-DD HH:MM UTC

5. Processing Workflow
   - Step 1: Read hourly TO3/TQV from source files
   - Step 2: Generate 10-min time steps (00,10,20,...,50)
   - Step 3: Use source data at whole hours, interpolate otherwise
   - Step 4: Parallel write to NetCDF (organized by year/month)
   - Key Technologies:
     * Caching: 48-hour data cache optimization
     * Parallelism: Multiprocessing (default 4 workers)
     * Fault Tolerance: Automatic missing data handling

6. Usage Notes
   - Directory Structure:
     /year/month/MERRA2_interp_*.nc (e.g. /2015/08/)
   - Global Coverage: All MERRA-2 grid points
   - Recommended Use Cases:
     * High-temporal-resolution atmospheric studies
     * Satellite data temporal matching
     * Model validation
   - Data Verification: Compare with original hourly data
   - Limitation: Prolonged data gaps may increase interpolation errors