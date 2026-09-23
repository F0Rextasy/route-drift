// Deliberately drifted demo app: every rule fires at least once.
const express = require("express");
const app = express();

app.get("/users", (req, res) => res.send("list"));
app.post("/users", (req, res) => res.send("created"));
app.get("/users/:id", (req, res) => res.send("one"));
app.delete("/users/:id", (req, res) => res.send("gone"));
app.get("/health", (req, res) => res.send("ok"));

// DRIFT 1 (method-mismatch): spec says GET /orders/{id}, code serves POST.
app.post("/orders/:id", (req, res) => res.send("order"));

// DRIFT 2 (missing-spec): no spec entry for DELETE /cache at all.
app.delete("/cache", (req, res) => res.send("flushed"));

// NOTE: GET /legacy is in the spec but implemented nowhere (missing-impl).
