from .SASTBase import SASTWithDocker
import time
import docker
import os
import _thread

def container_timeout(container_id, timeout = 3600):
    time.sleep(timeout)
    try:
        container = client.containers.get(container_id)
        container.stop()
    except:
        return

class Semgrep(SASTWithDocker):
    
    def __init__(self): 
        super().__init__()

            
    def __call__(self, target, output, with_dependency=False):
        
        # have been tested?
        if os.path.exists(output):
            if os.path.getsize(output) > 0:
                #already tested
                return 0
            
        global client
        client = docker.from_env()
        
        self.container = client.containers.run(
            detach=True,
            tty=True,
            # Temp: 60g exceeds available memory on the test machine
            mem_limit="12g",
            auto_remove=True,
            # MODIFIED: removed hardcoded SEMGREP_APP_TOKEN from the upstream
            # repository. The scan uses local rules via --config, so no
            # account token is required.
            image="semgrep:latest",
            command="/bin/bash"
        )
        
        if os.path.isfile(target):
            return self.test_file(target, output)
        elif os.path.isdir(target):
            return self.test_dir(target, output, with_dependency)


    def test_file(self, target, output):
        
        # create target folder
        self.container.exec_run(
                workdir="/",
                cmd='''/bin/bash -c "mkdir /target"''',
                tty=True
            )
        
        # copy target file
        self.put(self.container.id, target, "/target/")

        try:
            start_time = time.time()

            _thread.start_new_thread(container_timeout, (self.container.id, 3600))
            # MODIFIED: added --metrics=off, required once the app token is removed
            self.container.exec_run(
                cmd='''/bin/bash -c "semgrep scan --metrics=off --json-output=/result.json --config /rules/python /target"''',
                tty=True
            )

            end_time = time.time()
            
            # download result from docker container
            self.get(self.container.id, "/result.json", output)
            
            # remove container
            self.container.stop()
            
            return end_time - start_time
        
        except:
            
            return -1
    
    
    def test_dir(self, target, output, db, with_dependency):
        pass
    
    