export namespace api {
	
	export class LoginConfig {
	    url: string;
	    tenantId: string;
	
	    static createFrom(source: any = {}) {
	        return new LoginConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.url = source["url"];
	        this.tenantId = source["tenantId"];
	    }
	}
	export class OperationStatus {
	    code: string;
	    msg: string;
	
	    static createFrom(source: any = {}) {
	        return new OperationStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.code = source["code"];
	        this.msg = source["msg"];
	    }
	}
	export class User {
	    id: number;
	    username: string;
	    code: string;
	    nickName: string;
	    email: string;
	    phone: string;
	    gender: number;
	    status: number;
	    type: number;
	    tenantId: string;
	    delFlag: number;
	    createTime: string;
	    loginTime: string;
	    updateTime: string;
	
	    static createFrom(source: any = {}) {
	        return new User(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.username = source["username"];
	        this.code = source["code"];
	        this.nickName = source["nickName"];
	        this.email = source["email"];
	        this.phone = source["phone"];
	        this.gender = source["gender"];
	        this.status = source["status"];
	        this.type = source["type"];
	        this.tenantId = source["tenantId"];
	        this.delFlag = source["delFlag"];
	        this.createTime = source["createTime"];
	        this.loginTime = source["loginTime"];
	        this.updateTime = source["updateTime"];
	    }
	}
	export class PageResponse {
	    records: User[];
	    total: number;
	    size: number;
	    current: number;
	    pages: number;
	    orders: any[];
	
	    static createFrom(source: any = {}) {
	        return new PageResponse(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.records = this.convertValues(source["records"], User);
	        this.total = source["total"];
	        this.size = source["size"];
	        this.current = source["current"];
	        this.pages = source["pages"];
	        this.orders = source["orders"];
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
	
	export class UserDraft {
	    username: string;
	    password: string;
	    nickName: string;
	    email: string;
	    phone: string;
	
	    static createFrom(source: any = {}) {
	        return new UserDraft(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.username = source["username"];
	        this.password = source["password"];
	        this.nickName = source["nickName"];
	        this.email = source["email"];
	        this.phone = source["phone"];
	    }
	}

}

export namespace excel {
	
	export class ParseErr {
	    row: number;
	    column: string;
	    msg: string;
	
	    static createFrom(source: any = {}) {
	        return new ParseErr(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.row = source["row"];
	        this.column = source["column"];
	        this.msg = source["msg"];
	    }
	}
	export class ParsedRow {
	    row: number;
	    draft: api.UserDraft;
	    errors: string[];
	
	    static createFrom(source: any = {}) {
	        return new ParsedRow(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.row = source["row"];
	        this.draft = this.convertValues(source["draft"], api.UserDraft);
	        this.errors = source["errors"];
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
	export class ParseResult {
	    users: ParsedRow[];
	    errors: ParseErr[];
	    filename: string;
	
	    static createFrom(source: any = {}) {
	        return new ParseResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.users = this.convertValues(source["users"], ParsedRow);
	        this.errors = this.convertValues(source["errors"], ParseErr);
	        this.filename = source["filename"];
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

