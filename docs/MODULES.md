# Central SAP area registry

Stable IDs, names, categories, parents, aliases, icons and default colors live in `backend/module_registry.py`. The UI consumes this registry rather than maintaining separate icon/color maps. Local overrides change display name, approved icon, six-digit hex color and enabled status; IDs remain stable. Disabling hides an area from filter choices without deleting its roles.

This is a practical cross-version area vocabulary, not a claim that every item is an S/4HANA module. Products, technologies, functional areas, technical components and submodules are explicitly distinguished. For example, BASIS resolves to BC; FI-AA remains a child of FI; BTP and CRM remain products.

Official reference starting points: [SAP S/4HANA](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE), [SAP ERP](https://help.sap.com/docs/SAP_ERP). Live SAP Help retrieval was blocked by the cloud network proxy during this review. Consequently this registry has not been independently verified against current live SAP documentation; confirm product/version applicability before enterprise adoption.

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
