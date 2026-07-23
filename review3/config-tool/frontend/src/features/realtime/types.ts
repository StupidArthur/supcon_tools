export interface RealtimeSource {
  id: string
  name: string
  file: string
  replicas: number
}

export interface RealtimeProject {
  version: number
  id: string
  name: string
  sources: RealtimeSource[]
}

export interface ProjectSummary {
  id: string
  name: string
  sourceCount: number
}

export interface ExpandedInstance {
  name: string
  sourceId: string
  sourceFile: string
  replicaIndex: number
  originalName: string
}

export interface InstanceOrigin {
  sourceId: string
  sourceFile: string
  replicaIndex: number
  originalName: string
}

export interface DuplicateInstance {
  name: string
  occurrences: InstanceOrigin[]
}

export interface RealtimeValidationResult {
  valid: boolean
  instances: ExpandedInstance[]
  duplicates: DuplicateInstance[]
}

export interface RealtimeProjectView {
  project: RealtimeProject
  validation: RealtimeValidationResult
}
