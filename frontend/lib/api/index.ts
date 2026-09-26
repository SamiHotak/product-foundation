/** Public entry point: `import { api, unwrap, type Job } from "@/lib/api"`. */
import type { components } from "./schema";

export {
  api,
  ApiError,
  errorMessage,
  fieldErrors,
  isErrorResponse,
  NETWORK_ERROR_MESSAGE,
  toApiError,
  unwrap,
} from "./client";
export type { ErrorResponse } from "./client";

type Schemas = components["schemas"];

// Friendly names for the generated schema types.
export type Job = Schemas["JobRead"];
export type JobStatus = Schemas["JobStatus"];
export type ExampleJobCreate = Schemas["ExampleJobCreate"];
export type ReadinessResponse = Schemas["ReadinessResponse"];
export type DependencyCheck = Schemas["DependencyCheck"];
export type Me = Schemas["MeResponse"];
export type User = Schemas["UserRead"];
export type Organization = Schemas["OrganizationRead"];
export type AuthProviders = Schemas["AuthProviders"];
