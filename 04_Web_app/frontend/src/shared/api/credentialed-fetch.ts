/**
 * Sends browser API requests with the server-managed session cookie.
 *
 * The cookie remains HttpOnly: this helper only selects the Fetch credentials
 * mode and never reads or persists authentication state in JavaScript.
 */
export const AUTH_UNAUTHORIZED_EVENT = "mmm:auth-unauthorized";
export const AUTH_FORBIDDEN_EVENT = "mmm:auth-forbidden";

export interface CredentialedFetchOptions {
  /**
   * Login deliberately receives a 401 for invalid credentials and must not
   * treat it as an expired application session.
   */
  signalUnauthorized?: boolean;
  /**
   * Login can receive a 403 before a session exists. It must not trigger a
   * permission refresh for the protected application tree.
   */
  signalForbidden?: boolean;
}

export async function credentialedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: CredentialedFetchOptions = {},
): Promise<Response> {
  const response = await fetch(input, {
    ...init,
    credentials: "include",
  });
  if (
    response.status === 401 &&
    options.signalUnauthorized !== false &&
    typeof window !== "undefined"
  ) {
    window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT));
  }
  if (
    response.status === 403 &&
    options.signalForbidden !== false &&
    typeof window !== "undefined"
  ) {
    window.dispatchEvent(new CustomEvent(AUTH_FORBIDDEN_EVENT));
  }
  return response;
}
