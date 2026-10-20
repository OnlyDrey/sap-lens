# Central SAP area registry

Stable IDs, names, categories, parents, aliases, icons and default colors live in `backend/module_registry.py`. The UI consumes this registry rather than maintaining separate icon/color maps. Local overrides change display name, approved icon, six-digit hex color and enabled status; IDs remain stable. Disabling hides an area from filter choices without deleting its roles.

This is a practical cross-version area vocabulary, not a claim that every item is an S/4HANA module. Products, technologies, functional areas, technical components and submodules are explicitly distinguished. For example, BASIS resolves to BC; FI-AA remains a child of FI; BTP and CRM remain products.

Official reference starting points: [SAP S/4HANA](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE), [SAP ERP](https://help.sap.com/docs/SAP_ERP). On 2026-10-20, after initial cloud network restrictions cleared, the SAP Help search endpoint returned documentation titles/excerpts over verified HTTPS. The references below corroborate area names where a matching title was available. This is a terminology check, not exhaustive verification of release-specific availability or component hierarchy. The portal's browser renderer encountered the cloud certificate boundary.

WM and PA are familiar application shorthand: SAP references also use LE-WM and PA-PA respectively. Registry IDs are application vocabulary and do not claim to reproduce the complete SAP application-component hierarchy.

| ID | Name | Category | Parent | Aliases |
| --- | --- | --- | --- | --- |
| FI | Financial Accounting | module | — | Finance |
| FI-AA | Asset Accounting | submodule | FI | — |
| FI-AP | Accounts Payable | submodule | FI | — |
| FI-AR | Accounts Receivable | submodule | FI | — |
| CO | Controlling | module | — | — |
| CO-PA | Profitability Analysis | submodule | CO | — |
| TRM | Treasury and Risk Management | functional-area | — | — |
| FSCM | Financial Supply Chain Management | functional-area | — | — |
| BPC | SAP Business Planning and Consolidation | product | — | — |
| MM | Materials Management | module | — | — |
| MM-PUR | Purchasing | submodule | MM | — |
| MM-IM | Inventory Management | submodule | MM | — |
| SD | Sales and Distribution | module | — | — |
| LE | Logistics Execution | module | — | — |
| LE-TRA | Transportation | submodule | LE | — |
| WM | Warehouse Management | module | — | — |
| EWM | Extended Warehouse Management | functional-area | — | — |
| TM | Transportation Management | functional-area | — | — |
| SCM | SAP Supply Chain Management | product | — | — |
| APO | Advanced Planning and Optimization | component | SCM | — |
| SRM | SAP Supplier Relationship Management | product | — | — |
| PP | Production Planning and Control | module | — | — |
| PP-PI | Production Planning for Process Industries | submodule | PP | — |
| PM | Plant Maintenance | module | — | — |
| QM | Quality Management | module | — | — |
| PLM | Product Lifecycle Management | functional-area | — | — |
| EHS | Environment, Health and Safety | functional-area | — | — |
| EHSM | Environment, Health and Safety Management | functional-area | — | — |
| PS | Project System | module | — | — |
| RE-FX | Flexible Real Estate Management | functional-area | — | — |
| PSM | Public Sector Management | functional-area | — | — |
| CS | Customer Service | module | — | — |
| CRM | SAP Customer Relationship Management | product | — | — |
| HCM | Human Capital Management | product | — | SAP HCM |
| HR | Human Resources | module | HCM | — |
| PA | Personnel Administration | submodule | HR | — |
| OM | Organizational Management | submodule | HR | — |
| PY | Payroll | submodule | HR | — |
| CA | Cross-Application Components | component | — | — |
| BC | Basis Components | technical-component | — | BASIS |
| ABAP | ABAP Platform | technology | — | — |
| BW | SAP Business Warehouse | product | — | — |
| BI | Business Intelligence | functional-area | BW | — |
| GRC | Governance, Risk and Compliance | product | — | — |
| MDG | SAP Master Data Governance | product | — | — |
| DMS | Document Management | component | CA | — |
| BTP | SAP Business Technology Platform | product | — | — |
| IS-U | SAP Utilities | industry-solution | — | Utilities |
| UNCLASSIFIED | Unclassified | fallback | — | — |

## Live title references

| Area | SAP Help title |
| --- | --- |
| FI | [Financial Accounting (FI)](https://help.sap.com/docs/SAP_ERP/c17ab0bc78dc4a72960be5a4e564e8e8/c1d6e037bcae43858e23615c267a1bcb.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| FI-AA | [Asset Accounting (FI-AA)](https://help.sap.com/docs/SAP_ERP/fd4cb4c391f7467fa33f9febecad8e3a/0c8bd0531d8b4208e10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| FI-AP | [Accounts Payable (FI-AP)](https://help.sap.com/docs/SAP_ERP/96f425ef1b14444c93b34cb3b5406586/93b5d153e8b34208e10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.04.latest) |
| FI-AR | [Accounts Receivable (FI-AR)](https://help.sap.com/docs/SAP_ERP/33804bc801d742099c63a76ebca70a26/9b195f56ca030952e10000000a4450e5.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| CO | [Controlling (CO)](https://help.sap.com/docs/SAP_ERP/0c14fb2ee0f445d292f81a2a77e91bf4/cbb84c53d5ec7d77e10000000a441470.html?locale=en-US&state=PRODUCTION&version=6.17.latest) |
| CO-PA | [Profitability Analysis (CO-PA)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/5e23dc8fe9be4fd496f8ab556667ea05/f813d254fb26c50ae10000000a441470.html?locale=en-US&state=PRODUCTION&version=2025.002) |
| TRM | [Treasury and Risk Management - India (TRM)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/a960537583144eaeb4d94cad703f809d/4079d153da7e4308e10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=2025.002) |
| FSCM | [Financial Supply Chain Management (FSCM)](https://help.sap.com/docs/SAP_ERP/c6ef916aeac74db0a6bec2142bc00248/2e0d1c542b0ef57de10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| BPC | [Authorizations for SAP Business Planning and Consolidation (BPC)](https://help.sap.com/docs/ABAP_PLATFORM_NEW/209fa2ab94c44cccbf408f99def3ed2a/03914ae32bb74483a76bf091c4c0ce76.html?locale=en-US&state=PRODUCTION&version=202510.002) |
| MM | [Materials Management (MM)](https://help.sap.com/doc/00d4d153c9684608e10000000a174cb4/700_SFIN3E 006/en-US/3b5fd353c6244308e10000000a174cb4.html) |
| MM-PUR | [Purchasing (MM-PUR)](https://help.sap.com/docs/SAP_ERP/0db93e7d4fff428e99dab18abecb9305/5f3aa22859e04e3d917dfc3d969c5ff6.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| MM-IM | [Inventory Management (MM-IM)](https://help.sap.com/docs/SAP_ERP/b704a8db767040a08100adc846218964/2b0dc4530b29b44ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| SD | [Sales and Distribution (SD)](https://help.sap.com/docs/SAP_ERP_SPV/4178e608f1e4435ba7fc6f542ba1645a/b480d0531d8b4208e10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.06.37) |
| LE | [Logistics Execution (LE)](https://help.sap.com/docs/SAP_ERP/14e51959e063492e823242cc61884048/eb25fa512577bc64e10000000a423f68.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| LE-TRA | [Transportation (LE-TRA)](https://help.sap.com/docs/SAP_ERP/8a10bc7f4f3c4d64a22c819907ca1e57/9c93c95360267214e10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| WM | [Archiving Warehouse Management Records (LE-WM)](https://help.sap.com/docs/SAP_ERP/c6ef916aeac74db0a6bec2142bc00248/1188b6531de6b64ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| EWM | [Extended Warehouse Management (EWM)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9832125c23154a179bfa1784cdc9577a/4ecb88b8b2422afee10000000a42189e.html?locale=en-US&state=PRODUCTION&version=2025.002) |
| TM | [Transportation Management (TM)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/e3dc5400c1cc41d1bc0ae0e7fd9aa5a2/3dbac2009df0459da845e03e6802817f.html?locale=en-US&state=PRODUCTION&version=2025.002) |
| SCM | [SAP Supply Chain Management (SAP SCM)](https://help.sap.com/docs/SAP_SUPPLY_CHAIN_MANAGEMENT/e3b7b2e92a2549efbbd552a17b0d1341/4bbc40af1d493c1de10000000a42189b.html?locale=en-US&state=PRODUCTION&version=7.0.4) |
| APO | [SAP Advanced Planning and Optimization (APO)](https://help.sap.com/docs/SUPPORT_CONTENT/sapo/3354621778.html?locale=en-US&state=PRODUCTION&version=1.0) |
| PP | [Production Planning and Control (PP)](https://help.sap.com/docs/SAP_ERP/666b7ae6edfe4c05a90ac0150637f964/1725bf53d25ab64ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| PP-PI | [Production Planning for Process Industries (PP-PI)](https://help.sap.com/docs/SAP_ERP/a0d3efbac8b14fc89b29bf47a1677c86/e924ba53422bb54ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| PM | [Plant Maintenance (PM)](https://help.sap.com/docs/SAP_ERP/666b7ae6edfe4c05a90ac0150637f964/3868b65334e6b54ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| QM | [Quality Management (QM)](https://help.sap.com/docs/SAP_ERP/c4f650e3b4ad4c68bcee599cd1d10b07/f00fb753128eb44ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| PLM | [Product Lifecycle Management (PLM)](https://help.sap.com/docs/SAP_ERP/d99f293899c64e8aa5c5f57aa1bbf8f7/b54dd7531a4d424de10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| EHS | [Environment, Health and Safety (EHS)](https://help.sap.com/docs/SUPPORT_CONTENT/plm/3363506404.html?locale=en-US&state=PRODUCTION&version=1.0) |
| PS | [Project System (PS)](https://help.sap.com/docs/SUPPORT_CONTENT/prosys/3363505908.html?locale=en-US&state=PRODUCTION&version=1.0) |
| RE-FX | [Flexible Real Estate Management (RE-FX)](https://help.sap.com/docs/SAP_ERP/f2ef139b3fda4a09bbb90ebfb7850e7a/9d0a03b79b9742078acf1cbeb517dbda.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| PSM | [Integration with SAP Public Sector Management (PSM)](https://help.sap.com/docs/SAP_ERP/4d6b9b32599844ee81b23a443efedb7f/858fd65378024308e10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| CS | [Customer Service (CS)](https://help.sap.com/doc/2966b6531de6b64ce10000000a174cb4/700_SFIN3E 006/en-US/0e66b6531de6b64ce10000000a174cb4.html) |
| HCM | [SAP Human Capital Management for SAP S/4HANA](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f5d3e1005efd4e86acf9a65abf428082/95f26ca03e784a818d35b267b95d723b.html?locale=en-US&state=PRODUCTION&version=2022.000) |
| HR | [Data Transfer to Human Resources (HR)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/7c1ef52f3fea49d1944b266772379e52/e2e2e353a53d424de10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=2025.002) |
| PA | [Personnel Administration (PA-PA)](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/c6c3ffd90792427a9fee1a19df5b0925/e084b8535c39b44ce10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=2025.002) |
| OM | [Indirect Role Assignment Using Organizational Management (OM)](https://help.sap.com/docs/SAP_ERP/142f8559883b4c11966ebfb99dd61164/92e7623c28695c63e10000000a11405a.html?locale=en-US&state=PRODUCTION&version=6.05.latest) |
| CA | [Cross-Application Components (CA)](https://help.sap.com/docs/SAP_ERP/cf37e689fcbb4b67a4197897e0622b5f/fae4e4535dd4414de10000000a174cb4.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| ABAP | [RFC: ABAP Platform → ABAP Platform](https://help.sap.com/docs/ABAP_PLATFORM_NEW/e73bba71770e4c0ca5fb2a3c17e8e229/2803f4ad8d9d490c99a3e8a57551d264.html?locale=en-US&state=PRODUCTION&version=202510.002) |
| BW | [Integration with SAP Business Warehouse (BW)](https://help.sap.com/docs/SAP_ERP/bc455522154045329211cac2ce6b6c95/4a17455282a1d430e10000000a44538d.html?locale=en-US&state=PRODUCTION&version=6.18.latest) |
| BI | [Business Intelligence (BI) Manager](https://help.sap.com/docs/SAP_CONCUR/c4b0191a28a14341a112b65dbaa3ec8e/1c2da186700b1014a46a108435d32877.html?locale=en-US&state=PRODUCTION&version=2026_10) |
| GRC | [Preparing to Install SAP Solutions for Governance, Risk, and Compliance (GRC) 10.1](https://help.sap.com/docs/SAP_ACCESS_CONTROL/dec918a76e1246d386c51be8e6ca5bc8/ed7db251192f4420e10000000a423f68.html?locale=en-US&state=PRODUCTION&version=10.1.18) |
| MDG | [Integrating with SAP Master Data Governance (MDG)](https://help.sap.com/docs/SAP_MASTER_DATA_INTEGRATION/c7713d6177ad479d9ea00958db9f2f81/a9ef55b0339f4a88bc461edd5b78d75e.html?locale=en-US&state=PRODUCTION&version=CLOUD) |
| DMS | [Connecting to Document Management (DMS)](https://help.sap.com/docs/PLM_CP/fd39efd120a74b37a1acca61d63bacaf/6895ef3332fd4dbfa9311ddb58253ee9.html?locale=en-US&state=PRODUCTION&version=Cloud) |
| BTP | [Integration with SAP Business Technology Platform (BTP)](https://help.sap.com/docs/SAP_IM_StarterEdition/1f920a4c5eb34d21a5eaf5c3e280a24e/ba1b9c69d9ca4970be767d37d395eef4.html?locale=en-US&state=PRODUCTION&version=SHIP_SE) |

No matching descriptive title was established by the bounded first-three-results check for SRM, EHSM, CRM, PY, BC, IS-U. These entries require further product/version-specific verification; unrelated search hits were not treated as proof.
