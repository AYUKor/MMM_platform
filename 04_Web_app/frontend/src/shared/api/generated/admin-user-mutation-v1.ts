/* Generated from ../../contracts/admin_user_mutation_v1.schema.json. Do not edit manually. */

export type AdminUserMutationV1 = CreateLocalPilotUser | UpdateLocalPilotUser;

export interface CreateLocalPilotUser {
  email: string;
  display_name: string;
  password: string;
  role_id: "viewer" | "analyst" | "admin";
}
export interface UpdateLocalPilotUser {
  display_name?: string;
  role_id?: "viewer" | "analyst" | "admin";
}
