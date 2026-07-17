/* Generated from ../../contracts/admin_role_catalog_v1.schema.json. Do not edit manually. */

export interface AdminRoleCatalogV1 {
  contract_name: "admin_role_catalog_v1";
  schema_version: "1.0.0";
  catalog_version: "1.0.0";
  /**
   * @minItems 14
   * @maxItems 14
   */
  permissions: [
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission,
    Permission
  ];
  /**
   * @minItems 3
   * @maxItems 3
   */
  roles: [Role, Role, Role];
}
export interface Permission {
  permission_id: string;
  title: string;
  description: string;
}
export interface Role {
  role_id: "viewer" | "analyst" | "admin";
  title: string;
  description: string;
  permissions: string[];
}
