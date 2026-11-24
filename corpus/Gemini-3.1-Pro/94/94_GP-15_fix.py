import tornado.ioloop
import tornado.web
import json
import logging
import uuid
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('NetDash')

# In-memory storage for network events
NETWORK_EVENTS = [
    {"id": "ev_1", "source_ip": "192.168.1.10", "dest_ip": "10.0.0.5", "protocol": "TCP", "bytes": 1024, "status": "allowed"},
    {"id": "ev_2", "source_ip": "192.168.1.11", "dest_ip": "10.0.0.5", "protocol": "UDP", "bytes": 64, "status": "dropped"},
    {"id": "ev_3", "source_ip": "10.0.0.2", "dest_ip": "8.8.8.8", "protocol": "DNS", "bytes": 128, "status": "allowed"},
    {"id": "ev_4", "source_ip": "192.168.1.15", "dest_ip": "10.0.0.5", "protocol": "TCP", "bytes": 4096, "status": "allowed"},
]

class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Content-Type", 'application/json')
        self.set_header("Server", "NetDash-API/1.0")

    def write_error(self, status_code, **kwargs):
        self.finish(json.dumps({
            "error": {
                "code": status_code,
                "message": self._reason
            }
        }))

class HealthCheckHandler(BaseHandler):
    def get(self):
        """Simple health check endpoint"""
        self.write(json.dumps({
            "status": "healthy",
            "uptime": tornado.ioloop.IOLoop.current().time()
        }))

class EventListHandler(BaseHandler):
    def get(self):
        """Retrieve all network events"""
        self.write(json.dumps({
            "count": len(NETWORK_EVENTS),
            "events": NETWORK_EVENTS
        }))

class StaticFilterHandler(BaseHandler):
    def post(self):
        """Filter events using predefined static criteria"""
        try:
            body = json.loads(self.request.body)
            protocol = body.get("protocol")
            
            if not protocol:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing protocol"}))
                return
                
            filtered = [ev for ev in NETWORK_EVENTS if ev["protocol"] == protocol]
            self.write(json.dumps({
                "filter_type": "static",
                "match_count": len(filtered),
                "results": filtered
            }))
        except json.JSONDecodeError:
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid JSON body"}))

class AdvancedRuleHandler(BaseHandler):
    def post(self):
        """
        FIXED: CWE-94 Code Injection mitigated by removing exec().
        Replaced arbitrary code execution with a secure, structured JSON rule engine.
        """
        try:
            body = json.loads(self.request.body)
            rule_name = body.get("rule_name", f"rule_{uuid.uuid4().hex[:8]}")
            conditions = body.get("rule_conditions")

            if not conditions or not isinstance(conditions, list):
                self.set_status(400)
                self.write(json.dumps({"error": "rule_conditions is required and must be a list of criteria"}))
                return

            logger.info(f"Applying safe advanced rule: {rule_name}")
            
            # FIXED SINK: exec() removed. We now map structured JSON to native operators.
            # Example payload: 
            # [{"field": "bytes", "operator": "gt", "value": 1000}, {"field": "status", "operator": "eq", "value": "allowed"}]
            
            import operator
            allowed_operators = {
                'eq': operator.eq,
                'ne': operator.ne,
                'gt': operator.gt,
                'lt': operator.lt,
                'ge': operator.ge,
                'le': operator.le
            }

            filtered_events = []
            for event in NETWORK_EVENTS:
                match = True
                for cond in conditions:
                    field = cond.get("field")
                    op_str = cond.get("operator")
                    target_val = cond.get("value")
                    
                    if field not in event or op_str not in allowed_operators:
                        match = False
                        break
                        
                    op_func = allowed_operators[op_str]
                    try:
                        # Safely compare the event's field value against the target value
                        if not op_func(event[field], target_val):
                            match = False
                            break
                    except TypeError:
                        # Handle cases where types cannot be compared (e.g., int vs string)
                        match = False
                        break
                
                if match:
                    filtered_events.append(event)

            self.write(json.dumps({
                "rule_name": rule_name,
                "match_count": len(filtered_events),
                "results": filtered_events
            }))

        except json.JSONDecodeError:
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid JSON body format"}))
        except Exception as e:
            logger.error(f"Rule execution failed: {str(e)}")
            self.set_status(500)
            self.write(json.dumps({"error": "Internal server error during rule evaluation"}))

def make_app():
    return tornado.web.Application([
        (r"/api/v1/health", HealthCheckHandler),
        (r"/api/v1/events", EventListHandler),
        (r"/api/v1/events/filter/static", StaticFilterHandler),
        (r"/api/v1/events/filter/advanced", AdvancedRuleHandler),
    ], debug=False)

if __name__ == "__main__":
    app = make_app()
    port = 8888
    app.listen(port)
    logger.info(f"NetDash API listening on port {port}")
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        logger.info("Shutting down NetDash API")
        tornado.ioloop.IOLoop.current().stop()
