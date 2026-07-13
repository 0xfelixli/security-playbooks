---
title: Secure Docker Configurations
impact: HIGH
impactDescription: Container escapes and privilege escalation
tags: security, docker, containers, infrastructure, cwe-250
kind: infrastructure
detect:
  files: ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]
---

## Secure Docker Configurations

This guide provides security best practices for Dockerfiles and docker-compose configurations. Following these patterns helps prevent container escapes, privilege escalation, and other security vulnerabilities in containerized environments.

### Running as Root

The last user in the container should not be 'root'. If an attacker gains control of the container, they will have root access.

**Incorrect:**

```dockerfile
FROM debian:bookworm
RUN apt-get update && apt-get install -y some-package
USER appuser
USER root
```

**Correct:**

```dockerfile
FROM debian:bookworm
USER root
RUN apt-get update && apt-get install -y some-package
USER appuser
```

### Missing Image Version

Images should be tagged with an explicit version to produce deterministic container builds.

**Incorrect:**

```dockerfile
FROM debian
```

**Correct:**

```dockerfile
FROM debian:bookworm
```

### Using Latest Tag

The 'latest' tag may change the base container without warning, producing non-deterministic builds.

**Incorrect:**

```dockerfile
FROM debian:latest
```

**Correct:**

```dockerfile
FROM debian:bookworm
```

### Privileged Mode (Docker Compose)

Running containers in privileged mode grants the container the equivalent of root capabilities on the host machine. This can lead to container escapes, privilege escalation, and other security concerns.

**Incorrect:**

```yaml
version: "3.9"
services:
  worker:
    image: my-worker-image:1.0
    privileged: true
```

**Correct:**

```yaml
version: "3.9"
services:
  worker:
    image: my-worker-image:1.0
    privileged: false
```

### Exposing Docker Socket

Exposing the host's Docker socket to containers via a volume is equivalent to giving unrestricted root access to your host. Never expose the Docker socket unless absolutely necessary.

**Incorrect:**

```yaml
version: "3.9"
services:
  worker:
    image: my-worker-image:1.0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

**Correct (use a named volume instead of host mounts):**

```yaml
version: "3.9"
services:
  worker:
    image: my-worker-image:1.0
    volumes:
      - worker-data:/app/data
volumes:
  worker-data:
```

### Arbitrary Container Run (Python Docker SDK)

If unverified user data can reach the `run` or `create` method, it can result in running arbitrary containers.

**Incorrect:**

```python
import docker
client = docker.from_env()

def run_container(user_input):
    client.containers.run(user_input, 'echo hello world')
```

**Correct:**

```python
import docker
client = docker.from_env()

def run_container():
    client.containers.run("alpine", 'echo hello world')
```

## Not a Finding

- **`FROM scratch`**：多阶段构建的最终阶段使用 `FROM scratch` 无版本标签，是正常的极简镜像构建方式。
- **Docker-in-Docker（DinD）**：CI 系统中 `privileged: true` 配合明确注释说明用于 DinD 构建流水线，是已知的 CI 设计模式；仍应记录但不作为高危 finding。
- **Docker socket 只读挂载**：`/var/run/docker.sock:/var/run/docker.sock:ro` 的只读挂载不能阻止攻击，仍应报告；但如果是监控/观测工具（如 Portainer、ctop）且明确注释意图，降级为 MEDIUM。
- **`latest` 标签用于本地开发**：`docker-compose.yml` 中注释说明仅用于本地开发环境，不部署生产，降级处理。
- **USER 切换用于安装步骤**：构建阶段中途切换到 `root` 安装依赖后再切回非特权用户，只要最终 `USER` 不是 `root` 就不是问题。
