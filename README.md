# memoryHub

A production-ready, federated memory system for multi-agent AI applications.

## Overview

memoryHub is a comprehensive memory management system designed to serve as a central knowledge hub for multiple AI agents (local and remote). It combines semantic search, knowledge graphs, trust pipeline verification, and comprehensive monitoring to provide a reliable, scalable foundation for agent collaboration.

## Documentation

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Complete system architecture, components, and design (primary source of truth)
- **[API.md](./docs/API.md)** - REST API reference
- **[DEPLOYMENT.md](./docs/DEPLOYMENT.md)** - Deployment and setup guide
- **[TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)** - Diagnostics and troubleshooting

## Quick Start

```bash
git clone https://github.com/hleserg/memoryHub.git
cd memoryHub
make dev          # Run development server
# or
docker-compose up # Full stack with Redis + services
```

See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for detailed setup.

## Project Status

🔨 **Active Development** - Week 1: Storage, API Hub, Rate Limiting

## License

MemoryHub is licensed under the **MIT License**. See [LICENSE](./LICENSE) for details.

## Attributions

This project is built on excellent open source software. See [ATTRIBUTIONS.md](./ATTRIBUTIONS.md) for a complete list of dependencies and licenses.

## Community

- **Code of Conduct:** See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- **Contributing:** See [CONTRIBUTING.md](./CONTRIBUTING.md)
- **Security Issues:** See [SECURITY.md](./SECURITY.md)

---

**Primary source of truth:** [ARCHITECTURE.md](./ARCHITECTURE.md)
