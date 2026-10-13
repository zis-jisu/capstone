"""Read the ML graph directly from the existing Supabase SQL RPC.

Usage:
    python export_ml_rpc.py --check
    python export_ml_rpc.py --out graph_ml.json

Environment: SUPABASE_URL, SUPABASE_KEY (server-side service role only).
"""
import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def fetch_graph(url=None, key=None):
    url = (url or os.getenv('SUPABASE_URL', '')).rstrip('/')
    key = key or os.getenv('SUPABASE_KEY', '')
    if not url.startswith('https://') or not key:
        raise ValueError('Set SUPABASE_URL and backend-only SUPABASE_KEY')
    req = urllib.request.Request(
        url + '/rest/v1/rpc/get_graph_snapshot_ml',
        method='POST', data=b'{}',
        headers={'apikey': key, 'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            graph = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Graph RPC failed: HTTP {exc.code}') from None
    validate_graph(graph)
    return graph


def validate_graph(graph):
    required = ('metadata', 'nodes', 'edges', 'rgcn_tensors', 'validation')
    if not isinstance(graph, dict) or any(k not in graph for k in required):
        raise ValueError('RPC response is missing required graph keys')
    nodes, edges, tensors = graph['nodes'], graph['edges'], graph['rgcn_tensors']
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError('nodes and edges must be arrays')
    ids = [n['id'] for n in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate node IDs')
    mapping = tensors['node_id_to_idx']
    if len(mapping) != len(nodes) or any(mapping.get(node_id) != i for i, node_id in enumerate(ids)):
        raise ValueError('node_id_to_idx inconsistent with nodes')
    src, dst = tensors['edge_index']
    if len(src) != len(edges) or len(dst) != len(edges) or len(tensors['edge_type']) != len(edges):
        raise ValueError('Edge tensor lengths do not match')
    if len(tensors['node_type']) != len(nodes):
        raise ValueError('Node tensor length does not match')
    if any(not isinstance(i, int) or i < 0 or i >= len(nodes) for i in src + dst):
        raise ValueError('Edge tensor contains invalid node index')
    for i, edge in enumerate(edges):
        if mapping.get(edge['source']) != src[i] or mapping.get(edge['target']) != dst[i]:
            raise ValueError('Edge order differs from edge_index')
    if graph['metadata']['num_nodes'] != len(nodes) or graph['metadata']['num_edges'] != len(edges):
        raise ValueError('Metadata count mismatch')
    if graph['validation'].get('invalid_edges'):
        raise ValueError('RPC reported invalid edges')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Only check the RPC output')
    parser.add_argument('--out', help='Optional local JSON output for debugging')
    args = parser.parse_args()
    graph = fetch_graph()
    print('Graph validated: nodes={}, edges={}'.format(len(graph['nodes']), len(graph['edges'])))
    if args.out:
        Path(args.out).write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    elif not args.check:
        print('No file written. Use --out only if a local export is needed.')


if __name__ == '__main__':
    main()
