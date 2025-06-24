H8SR 地表反射率产品说明
====================

1. 文件命名规则
   - 格式: SR_YYYYMMDD_HHMM.nc
     示例: SR_20150801_0250.nc
   - 说明:
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * MM: 分钟 (2位数字)

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度: 2 (站点维度和波段维度)
   - 变量: 4个
   - 文件大小: 约300-500 KB

3. 数据内容
   | 变量名                | 描述                                  | 单位 | 数据类型 | 维度            |
   |-----------------------|---------------------------------------|------|----------|-----------------|
   | station               | 站点名称                             | 无   | 字符串   | station         |
   | General_availability  | 数据可用性标志 (0:晴空陆地可用, 1:不可用) | 无   | int8     | station         |
   | surface_reflectance   | 地表反射率(6波段)                   | 1    | float32  | (station, band) |
   | valid_flag            | 处理成功标志 (1:成功, 0:失败)        | 无   | int8     | station         |

4. 数据处理说明
   - 数据来源:
     * TOA反射率: H8 L1产品 (Albedo_01-06)
     * 几何角度: H8 L1产品 (SAZ, SAA, SOZ, SOA)
     * 气溶胶光学厚度: H8 L2 ARP产品 (AOT)
     * 大气参数: MERRA-2再分析数据 (TO3, TQV)
     * 土地覆盖类型: MODIS MCD12Q1产品
   - 处理流程:
     1) 数据可用性判断: 基于L2ARP产品的Data_Availability、Cloud_Flag和Land_Water_Flag生成General_availability标志
     2) 大气校正: 使用6S辐射传输模型，输入TOA反射率、几何角度、AOD、臭氧和可降水量，计算地表反射率
     3) BRDF归一化: 根据土地覆盖类型选择对应的BRDF模型(Rahman, Walthall或Lambertian)进行归一化
   - 数据质量:
     * 有效值范围: 0.0-1.0
     * 缺失值: NaN (当General_availability=1或处理失败时)
     * 典型有效数据比例: 约30-70%(取决于云覆盖情况)

5. 数据来源
   - 卫星: 日本气象厅向日葵8号(Himawari-8)
   - 辅助数据: NASA MERRA-2再分析数据、MODIS MCD12Q1土地覆盖数据
   - 处理软件: Py6S辐射传输模型

6. 使用注意事项
   - 本产品仅包含陆地晴空条件下的地表反射率
   - 冰雪覆盖区域可能因BRDF模型简化而存在不确定性
   - 城市区域因地表异质性影响精度

----------------------------------------------------------------

H8SR Surface Reflectance Product Documentation
==============================================

1. File Naming Convention
   - Format: SR_YYYYMMDD_HHMM.nc
     Example: SR_20150801_0250.nc
   - Description:
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * MM: Minute (2-digit)

2. File Format
   - Format Type: NetCDF-4
   - Dimensions: 2 (station and band)
   - Variables: 4
   - File Size: ~300-500 KB

3. Data Content
   | Variable               | Description                             | Unit | Data Type | Dimensions       |
   |------------------------|-----------------------------------------|------|-----------|------------------|
   | station                | Station names                           | None | String    | station          |
   | General_availability   | Data availability flag (0: clear land available, 1: unavailable) | None | int8      | station          |
   | surface_reflectance    | Surface reflectance (6 bands)           | 1    | float32   | (station, band)  |
   | valid_flag             | Processing success flag (1: success, 0: failure) | None | int8      | station          |

4. Data Processing Notes
   - Data Sources:
     * TOA reflectance: H8 L1 product (Albedo_01-06)
     * Geometry angles: H8 L1 product (SAZ, SAA, SOZ, SOA)
     * Aerosol optical thickness: H8 L2 ARP product (AOT)
     * Atmospheric parameters: MERRA-2 reanalysis (TO3, TQV)
     * Land cover type: MODIS MCD12Q1 product
   - Processing Flow:
     1) Data availability: Generate General_availability flag based on L2ARP's Data_Availability, Cloud_Flag and Land_Water_Flag
     2) Atmospheric correction: Use 6S radiative transfer model with inputs of TOA reflectance, geometry, AOD, ozone and water vapor
     3) BRDF normalization: Apply BRDF model (Rahman, Walthall or Lambertian) according to land cover type
   - Data Quality:
     * Valid range: 0.0-1.0
     * Missing value: NaN (when General_availability=1 or processing failed)
     * Typical valid data ratio: ~30-70% (depending on cloud coverage)

5. Data Source
   - Satellite: JMA Himawari-8
   - Auxiliary data: NASA MERRA-2 reanalysis, MODIS MCD12Q1 land cover
   - Processing software: Py6S radiative transfer model

6. Usage Notes
   - This product contains land surface reflectance under clear-sky conditions only
   - Snow/ice covered areas may have uncertainties due to simplified BRDF model
   - Urban areas may be affected by surface heterogeneity