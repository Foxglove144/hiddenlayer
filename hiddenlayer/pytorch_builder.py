"""
HiddenLayer

PyTorch graph importer.
 
Written by Waleed Abdulla
Licensed under the MIT License
"""

from __future__ import absolute_import, division, print_function
import re
from .graph import Graph, Node
from . import transforms as ht
import torch

# PyTorch Graph Transforms
FRAMEWORK_TRANSFORMS = [
    # Hide onnx: prefix
    ht.Rename(op=r"onnx::(.*)", to=r"\1"),
    # ONNX uses Gemm for linear layers (stands for General Matrix Multiplication).
    # It's an odd name that noone recognizes. Rename it. 
    ht.Rename(op=r"Gemm", to=r"Linear"),
    # PyTorch layers that don't have an ONNX counterpart
    ht.Rename(op=r"aten::max\_pool2d\_with\_indices", to="MaxPool"),
    # Shorten op name
    ht.Rename(op=r"BatchNormalization", to="BatchNorm"),
]

# https://github.com/pytorch/pytorch/blob/2efe4d809fdc94501fc38bf429e9a8d4205b51b6/torch/utils/tensorboard/_pytorch_graph.py#L384
def _node_get(node: torch._C.Node, key: str):
    """Gets attributes of a node which is polymorphic over return type."""
    sel = node.kindOf(key)
    return getattr(node, sel)(key)

torch._C.Node.__getitem__ = _node_get

def dump_pytorch_graph(graph):
    """List all the nodes in a PyTorch graph."""
    f = "{:25} {:40}   {} -> {}"
    print(f.format("kind", "scopeName", "inputs", "outputs"))
    for node in graph.nodes():
        print(f.format(node.kind(), node.scopeName(),
                       [i.unique() for i in node.inputs()],
                       [i.unique() for i in node.outputs()]
                       ))


def pytorch_id(node):
    """Returns a unique ID for a node."""
    # After ONNX simplification, the scopeName is not unique anymore
    # so append node outputs to guarantee uniqueness
    return node.scopeName() + "/outputs/" + "/".join(["{}".format(o.unique()) for o in node.outputs()])


def get_shape(torch_node):
    try:
        shape = torch_node.output().type().sizes()
    except:
        shape = None
    return shape


def import_graph(hl_graph, model, args, input_names=None, verbose=False):
    # TODO: add input names to graph

    # Run the Pytorch graph to get a trace and generate a graph from it
    trace, out = torch.jit._get_trace_graph(model, args)
    torch_graph = torch.onnx._optimize_graph(trace, torch.onnx.OperatorExportTypes.ONNX)

    # Dump list of nodes (DEBUG only)
    if verbose:
        dump_pytorch_graph(torch_graph)

    # Loop through nodes and build HL graph
    for torch_node in torch_graph.nodes():
        # Op
        op = torch_node.kind()
        # Parameters
        params = {k: torch_node[k] for k in torch_node.attributeNames()}
        # Inputs/outputs
        # TODO: inputs = [i.unique() for i in node.inputs()]
        outputs = [o.unique() for o in torch_node.outputs()]
        # Get output shape
        shape = get_shape(torch_node)
        # Add HL node
        hl_node = Node(uid=pytorch_id(torch_node), name=None, op=op, 
                       output_shape=shape, params=params)
        hl_graph.add_node(hl_node)
        # Add edges
        for target_torch_node in torch_graph.nodes():
            target_inputs = [i.unique() for i in target_torch_node.inputs()]
            if set(outputs) & set(target_inputs):
                hl_graph.add_edge_by_id(pytorch_id(torch_node), pytorch_id(target_torch_node), shape)
    return hl_graph
