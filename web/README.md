# ReturnIQ web

React + TypeScript + Vite test console: Flow A (customer return form, reviewer queue, review screen) and Flow B
(Seller tab: My Products, product report with progress steps and clickable evidence, Q&A chat).

```bash
cd web
npm install
npm run dev        # http://localhost:5173
```

It talks to the API at `http://localhost:8000`; set `VITE_API_URL` to change that. Start the backend first (see [`../server`](../server/README.md)). Full instructions are in the [root README](../README.md).
