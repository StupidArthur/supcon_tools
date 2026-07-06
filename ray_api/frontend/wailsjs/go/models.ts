export namespace collector {
	
	export class Snapshot {
	    cluster: model.ClusterMetric;
	    nodes: model.NodeMetric[];
	    workers: model.WorkerSnapshot[];
	    actors: model.ActorSnapshot[];
	    jobs: model.JobSnapshot[];
	
	    static createFrom(source: any = {}) {
	        return new Snapshot(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.cluster = this.convertValues(source["cluster"], model.ClusterMetric);
	        this.nodes = this.convertValues(source["nodes"], model.NodeMetric);
	        this.workers = this.convertValues(source["workers"], model.WorkerSnapshot);
	        this.actors = this.convertValues(source["actors"], model.ActorSnapshot);
	        this.jobs = this.convertValues(source["jobs"], model.JobSnapshot);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace config {
	
	export class ClusterConfig {
	    id: string;
	    platformUrl: string;
	
	    static createFrom(source: any = {}) {
	        return new ClusterConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.platformUrl = source["platformUrl"];
	    }
	}
	export class Thresholds {
	    nodeCpu: number;
	    nodeMem: number;
	    nodeGpu: number;
	    workerCpu: number;
	    workerMem: number;
	    workerGpu: number;
	
	    static createFrom(source: any = {}) {
	        return new Thresholds(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.nodeCpu = source["nodeCpu"];
	        this.nodeMem = source["nodeMem"];
	        this.nodeGpu = source["nodeGpu"];
	        this.workerCpu = source["workerCpu"];
	        this.workerMem = source["workerMem"];
	        this.workerGpu = source["workerGpu"];
	    }
	}
	export class Config {
	    clusters: ClusterConfig[];
	    dbPath: string;
	    logDir: string;
	    sortBy: string;
	    sampleEvery: number;
	    thresholds: Thresholds;
	    timeoutSec?: number;
	    concurrency?: number;
	    globalConcurrency?: number;
	    recoverConsecutive?: number;
	
	    static createFrom(source: any = {}) {
	        return new Config(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.clusters = this.convertValues(source["clusters"], ClusterConfig);
	        this.dbPath = source["dbPath"];
	        this.logDir = source["logDir"];
	        this.sortBy = source["sortBy"];
	        this.sampleEvery = source["sampleEvery"];
	        this.thresholds = this.convertValues(source["thresholds"], Thresholds);
	        this.timeoutSec = source["timeoutSec"];
	        this.concurrency = source["concurrency"];
	        this.globalConcurrency = source["globalConcurrency"];
	        this.recoverConsecutive = source["recoverConsecutive"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace main {
	
	export class HistoryRange {
	    from: number;
	    to: number;
	
	    static createFrom(source: any = {}) {
	        return new HistoryRange(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.from = source["from"];
	        this.to = source["to"];
	    }
	}
	export class SaveConfigResult {
	    success: boolean;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new SaveConfigResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.error = source["error"];
	    }
	}

}

export namespace model {
	
	export class ActorEvent {
	    ts: number;
	    clusterId: string;
	    actorId: string;
	    actorClass: string;
	    prevState: string;
	    newState: string;
	    deathCause: string;
	
	    static createFrom(source: any = {}) {
	        return new ActorEvent(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts = source["ts"];
	        this.clusterId = source["clusterId"];
	        this.actorId = source["actorId"];
	        this.actorClass = source["actorClass"];
	        this.prevState = source["prevState"];
	        this.newState = source["newState"];
	        this.deathCause = source["deathCause"];
	    }
	}
	export class ActorSnapshot {
	    ts: number;
	    clusterId: string;
	    nodeId: string;
	    actorId: string;
	    actorClass: string;
	    name: string;
	    state: string;
	    numRestarts: number;
	    jobId: string;
	    pid: number;
	    ipAddress: string;
	    numExecTasks: number;
	    gpuUsed: number;
	    exitDetail: string;
	
	    static createFrom(source: any = {}) {
	        return new ActorSnapshot(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts = source["ts"];
	        this.clusterId = source["clusterId"];
	        this.nodeId = source["nodeId"];
	        this.actorId = source["actorId"];
	        this.actorClass = source["actorClass"];
	        this.name = source["name"];
	        this.state = source["state"];
	        this.numRestarts = source["numRestarts"];
	        this.jobId = source["jobId"];
	        this.pid = source["pid"];
	        this.ipAddress = source["ipAddress"];
	        this.numExecTasks = source["numExecTasks"];
	        this.gpuUsed = source["gpuUsed"];
	        this.exitDetail = source["exitDetail"];
	    }
	}
	export class Alert {
	    id: number;
	    clusterId: string;
	    clusterName: string;
	    nodeName: string;
	    objectType: string;
	    objectId: string;
	    objectName: string;
	    metric: string;
	    threshold: number;
	    recovered: boolean;
	    acknowledged: boolean;
	    firstTriggerTs: number;
	    lastTriggerTs: number;
	    recoverTs: number;
	    ackTs: number;
	    eliminatedTs: number;
	    lastValue: number;
	
	    static createFrom(source: any = {}) {
	        return new Alert(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.clusterId = source["clusterId"];
	        this.clusterName = source["clusterName"];
	        this.nodeName = source["nodeName"];
	        this.objectType = source["objectType"];
	        this.objectId = source["objectId"];
	        this.objectName = source["objectName"];
	        this.metric = source["metric"];
	        this.threshold = source["threshold"];
	        this.recovered = source["recovered"];
	        this.acknowledged = source["acknowledged"];
	        this.firstTriggerTs = source["firstTriggerTs"];
	        this.lastTriggerTs = source["lastTriggerTs"];
	        this.recoverTs = source["recoverTs"];
	        this.ackTs = source["ackTs"];
	        this.eliminatedTs = source["eliminatedTs"];
	        this.lastValue = source["lastValue"];
	    }
	}
	export class ClusterMetric {
	    ts: number;
	    clusterId: string;
	    cpuTotal: number;
	    cpuUsed: number;
	    memTotal: number;
	    memUsed: number;
	    gpuTotal: number;
	    gpuUsed: number;
	    heartbeatMax: number;
	    gzipSupported: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ClusterMetric(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts = source["ts"];
	        this.clusterId = source["clusterId"];
	        this.cpuTotal = source["cpuTotal"];
	        this.cpuUsed = source["cpuUsed"];
	        this.memTotal = source["memTotal"];
	        this.memUsed = source["memUsed"];
	        this.gpuTotal = source["gpuTotal"];
	        this.gpuUsed = source["gpuUsed"];
	        this.heartbeatMax = source["heartbeatMax"];
	        this.gzipSupported = source["gzipSupported"];
	    }
	}
	export class CollectorStatus {
	    running: boolean;
	    lastSuccessTs: number;
	    errCount: number;
	    lastError: string;
	
	    static createFrom(source: any = {}) {
	        return new CollectorStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.running = source["running"];
	        this.lastSuccessTs = source["lastSuccessTs"];
	        this.errCount = source["errCount"];
	        this.lastError = source["lastError"];
	    }
	}
	export class GlobalPerf {
	    clusterCount: number;
	    runningClusters: number;
	    clustersWithError: number;
	    totalNodes: number;
	    totalWorkers: number;
	    totalActors: number;
	    totalDetailReqs: number;
	    maxDetailMs: number;
	    globalConcurrency: number;
	    procMemBytes: number;
	    procGoroutine: number;
	    updatedAt: number;
	
	    static createFrom(source: any = {}) {
	        return new GlobalPerf(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.clusterCount = source["clusterCount"];
	        this.runningClusters = source["runningClusters"];
	        this.clustersWithError = source["clustersWithError"];
	        this.totalNodes = source["totalNodes"];
	        this.totalWorkers = source["totalWorkers"];
	        this.totalActors = source["totalActors"];
	        this.totalDetailReqs = source["totalDetailReqs"];
	        this.maxDetailMs = source["maxDetailMs"];
	        this.globalConcurrency = source["globalConcurrency"];
	        this.procMemBytes = source["procMemBytes"];
	        this.procGoroutine = source["procGoroutine"];
	        this.updatedAt = source["updatedAt"];
	    }
	}
	export class JobSnapshot {
	    ts: number;
	    clusterId: string;
	    jobId: string;
	    status: string;
	    startTime: number;
	    endTime: number;
	    errorType: string;
	    entry: string;
	
	    static createFrom(source: any = {}) {
	        return new JobSnapshot(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts = source["ts"];
	        this.clusterId = source["clusterId"];
	        this.jobId = source["jobId"];
	        this.status = source["status"];
	        this.startTime = source["startTime"];
	        this.endTime = source["endTime"];
	        this.errorType = source["errorType"];
	        this.entry = source["entry"];
	    }
	}
	export class NodeMetric {
	    ts: number;
	    clusterId: string;
	    nodeId: string;
	    hostname: string;
	    ip: string;
	    isHead: boolean;
	    state: string;
	    cpu: number;
	    memTotal: number;
	    memUsed: number;
	    gpuTotal: number;
	    gpuUsed: number;
	    isPartial: boolean;
	
	    static createFrom(source: any = {}) {
	        return new NodeMetric(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts = source["ts"];
	        this.clusterId = source["clusterId"];
	        this.nodeId = source["nodeId"];
	        this.hostname = source["hostname"];
	        this.ip = source["ip"];
	        this.isHead = source["isHead"];
	        this.state = source["state"];
	        this.cpu = source["cpu"];
	        this.memTotal = source["memTotal"];
	        this.memUsed = source["memUsed"];
	        this.gpuTotal = source["gpuTotal"];
	        this.gpuUsed = source["gpuUsed"];
	        this.isPartial = source["isPartial"];
	    }
	}
	export class PerfMetrics {
	    summaryMs: number;
	    detailMs: number;
	    detailNodesMs: number;
	    detailMaxNodeMs: number;
	    nodeCount: number;
	    workerCount: number;
	    actorCount: number;
	    detailReqs: number;
	    slowNodeId: string;
	    slowNodeHost: string;
	    slowNodeMs: number;
	    procMemBytes: number;
	    procGoroutine: number;
	    concurrency: number;
	    risk: string;
	
	    static createFrom(source: any = {}) {
	        return new PerfMetrics(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.summaryMs = source["summaryMs"];
	        this.detailMs = source["detailMs"];
	        this.detailNodesMs = source["detailNodesMs"];
	        this.detailMaxNodeMs = source["detailMaxNodeMs"];
	        this.nodeCount = source["nodeCount"];
	        this.workerCount = source["workerCount"];
	        this.actorCount = source["actorCount"];
	        this.detailReqs = source["detailReqs"];
	        this.slowNodeId = source["slowNodeId"];
	        this.slowNodeHost = source["slowNodeHost"];
	        this.slowNodeMs = source["slowNodeMs"];
	        this.procMemBytes = source["procMemBytes"];
	        this.procGoroutine = source["procGoroutine"];
	        this.concurrency = source["concurrency"];
	        this.risk = source["risk"];
	    }
	}
	export class WorkerSnapshot {
	    ts: number;
	    clusterId: string;
	    nodeId: string;
	    pid: number;
	    jobId: string;
	    processName: string;
	    cpuPercent: number;
	    memRss: number;
	    numFds: number;
	    language: string;
	    gpuUsed: number;
	
	    static createFrom(source: any = {}) {
	        return new WorkerSnapshot(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ts = source["ts"];
	        this.clusterId = source["clusterId"];
	        this.nodeId = source["nodeId"];
	        this.pid = source["pid"];
	        this.jobId = source["jobId"];
	        this.processName = source["processName"];
	        this.cpuPercent = source["cpuPercent"];
	        this.memRss = source["memRss"];
	        this.numFds = source["numFds"];
	        this.language = source["language"];
	        this.gpuUsed = source["gpuUsed"];
	    }
	}

}

