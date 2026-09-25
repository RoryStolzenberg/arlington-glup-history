// Standardized-colors viewer config. The palette and aliases mirror
// scripts/standardize.py (which renders the tiles) — keep them identical.
window.VIEWER_CONFIG = {
  "dataBase": "../",
  "legendTitle": "Legend (all years)",
  "canon": [
    {
      "code": "res-low",
      "name": "Res Low  (0-10 u/ac)",
      "color": "#f2e88c"
    },
    {
      "code": "res-low-11-15",
      "name": "Res Low  (11-15 u/ac)",
      "color": "#e6c944"
    },
    {
      "code": "res-lowmed",
      "name": "Res Low-Medium  (16-36)",
      "color": "#e89e54"
    },
    {
      "code": "res-med",
      "name": "Res Medium  (37-72)",
      "color": "#c97b4a"
    },
    {
      "code": "res-highmed",
      "name": "Res High-Medium  (3.24 FAR)",
      "color": "#8c4a2f"
    },
    {
      "code": "res-high",
      "name": "Res High  (4.8 FAR)",
      "color": "#521c1c"
    },
    {
      "code": "svc-commercial",
      "name": "Service Commercial",
      "color": "#f28c9c"
    },
    {
      "code": "com-general",
      "name": "General Commercial",
      "color": "#d92b2b"
    },
    {
      "code": "svc-industry",
      "name": "Industrial / Service Industry",
      "color": "#c9308f"
    },
    {
      "code": "public",
      "name": "Public / Semi-Public",
      "color": "#74c169"
    },
    {
      "code": "gov-community",
      "name": "Government & Community",
      "color": "#b5b294"
    },
    {
      "code": "oah-low",
      "name": "Off-Apt-Hotel Low",
      "color": "#a8d4ee"
    },
    {
      "code": "oah-med",
      "name": "Off-Apt-Hotel Medium",
      "color": "#4a9ede"
    },
    {
      "code": "oah-high",
      "name": "Off-Apt-Hotel High",
      "color": "#1f5fb0"
    },
    {
      "code": "mu-med",
      "name": "Mixed-Use Medium",
      "color": "#d9a8d9"
    },
    {
      "code": "mu-highmed",
      "name": "Mixed-Use High-Medium",
      "color": "#a55fc0"
    },
    {
      "code": "mu-coord",
      "name": "Coordinated Mixed-Use",
      "color": "#6a1f9e"
    }
  ],
  "alias": {
    "res-low-1-10": "res-low",
    "res-lowmed@60s": "res-low-11-15",
    "res-highmed@60s": "res-lowmed",
    "apt-office": "oah-med",
    "com-office": "oah-high",
    "com-neighborhood": "svc-commercial",
    "industrial": "svc-industry",
    "greenway": "public",
    "semi-public": "public"
  }
};
