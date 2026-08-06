export namespace team {
	
	export class Machine {
	    zkjs: string;
	    cloudId: string;
	
	    static createFrom(source: any = {}) {
	        return new Machine(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.zkjs = source["zkjs"];
	        this.cloudId = source["cloudId"];
	    }
	}
	export class Team {
	    seq: number;
	    name: string;
	    tenantId: string;
	    username: string;
	    machine: Machine;
	    ip: string;
	    type: string;
	
	    static createFrom(source: any = {}) {
	        return new Team(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.seq = source["seq"];
	        this.name = source["name"];
	        this.tenantId = source["tenantId"];
	        this.username = source["username"];
	        this.machine = this.convertValues(source["machine"], Machine);
	        this.ip = source["ip"];
	        this.type = source["type"];
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

