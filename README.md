# Pulse

Pulse is an intranet status platform. A hub page summarizes everything, and each
kind of resource is its own product on a subdomain:

| Product | Example host | Shows | Collector |
|---|---|---|---|
| Hub | `status.example.edu` | One-line summary from every product the viewer may see | Reads each product's `/api/summary` |
| ComputersPulse | `computers.status.example.edu` | Shared computers (labs, open-access stations, kiosks, podiums): free, in use or offline, on floorplans | Small agent on each Mac and Windows machine |
| PrintersPulse | `printers.status.example.edu` | Printer state, queues and supplies | Pulls from the print-management API |
| ServersPulse | `servers.status.example.edu` | Server and service health, for a restricted audience | Pulls from existing monitoring |

Every page sits behind single sign-on, and each product declares the audience
role it requires.

## Layout (planned)

- `core/`: event contract, space catalog schema, web shell, and the `pulse-product` Terraform module
- `hub/`: the summary page
- `products/computers/`: `agent-mac`, `agent-win`, `api`, `web`
- `products/printers/`, `products/servers/`

This repo holds only generic code. Site-specific values (hostnames, catalogs,
floorplans, tenant settings) are configuration that a separate deploy repo supplies.

## License

MIT
