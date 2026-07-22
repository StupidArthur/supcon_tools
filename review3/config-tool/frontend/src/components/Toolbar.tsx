/**
 * Legacy Toolbar shim — primary navigation lives in AppNav.
 * Kept as a thin re-export so old imports still resolve; stage_0 acceptance
 * asserting removed primary labels is expected to fail after this refactor.
 */
export { AppNav as Toolbar } from '../features/app/AppNav'
