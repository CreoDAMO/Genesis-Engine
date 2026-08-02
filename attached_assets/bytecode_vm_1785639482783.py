"""
Genesis Engine — Tiny Domain-Specific Bytecode VM
=================================================
Hard containment boundary for evolved strategy expression trees.

Every strategy is compiled from AST → compact bytecode and executed
only inside this VM. The VM provides:

  - Instruction fuel metering (hard limit, no infinite loops possible)
  - Fixed-size stack (no heap allocation by strategies)
  - Explicit feature vector only (no closures, no globals, no I/O)
  - Deterministic execution
  - Zero host capabilities

This replaces unrestricted Python evaluation and is the substrate
that a later Wasmtime lowering would also target.
"""

from __future__ import annotations

import ast
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List, Optional, Sequence, Tuple
import math


# ---------------------------------------------------------------------------
# Opcodes
# ---------------------------------------------------------------------------

class Op(IntEnum):
    # stack
    PUSH_CONST   = 1
    PUSH_FEAT    = 2          # index into feature vector
    # unary
    NEG          = 10
    ABS          = 11
    LOG          = 12
    EXP          = 13
    CLIP         = 14         # hard clip to [-1, 1]
    SIGN         = 15
    # binary
    ADD          = 20
    SUB          = 21
    MUL          = 22
    DIV          = 23
    MAX          = 24
    MIN          = 25
    GT           = 26
    LT           = 27
    # ternary
    IF_ELSE      = 30         # (cond, then, else) — cond > 0.5 → then else else
    # control / end
    RET          = 255


# Human-readable names for debugging
OP_NAMES = {op.value: op.name for op in Op}


# ---------------------------------------------------------------------------
# Compiler: AST → bytecode
# ---------------------------------------------------------------------------

# Map function names used by the genetic engine to opcodes
FUNC_TO_OP = {
    "neg": Op.NEG,
    "abs": Op.ABS,
    "log": Op.LOG,
    "exp": Op.EXP,
    "clip": Op.CLIP,
    "sign": Op.SIGN,
    "add": Op.ADD,
    "sub": Op.SUB,
    "mul": Op.MUL,
    "div": Op.DIV,
    "max": Op.MAX,
    "min": Op.MIN,
    "gt": Op.GT,
    "lt": Op.LT,
    "if_else": Op.IF_ELSE,
}

# Feature name → index (must stay in sync with FEATURE_KEYS in genetic engine)
# Indices 0-9  : original market microstructure
# Indices 10-13: synthetic causal / intervention terminals
# Indices 14-15: regime indicators
FEATURE_INDEX = {
    "mid": 0,
    "spread": 1,
    "imbalance": 2,
    "volume": 3,
    "rsi": 4,
    "zscore": 5,
    "momentum": 6,
    "volatility": 7,
    "time_frac": 8,
    "prev_signal": 9,
    # Causal / intervention-style terminals (synthetic DAG)
    "do_imbalance": 10,      # interventional imbalance (do(imbalance)=x)
    "causal_mid": 11,        # estimated P(mid shift | do(imbalance))
    "shock": 12,             # exogenous shock intensity
    "confounder": 13,        # unobserved-style common cause (for sensitivity)
    # Regime
    "regime": 14,            # 0 = calm, 1 = stress
    "regime_age": 15,        # steps since last regime change
}


@dataclass
class CompiledStrategy:
    """Bytecode + metadata for one genome."""
    code: bytes                 # packed bytecode
    consts: List[float]         # constant pool
    source: str
    complexity: int
    n_ops: int                  # number of opcodes (for fuel accounting)


class CompileError(Exception):
    pass


def _emit(op: Op, arg: int = 0) -> bytes:
    """Each instruction is 1 byte opcode + 2 byte little-endian arg."""
    return struct.pack("<BH", op.value, arg & 0xFFFF)


def compile_ast(tree: ast.AST, source: str = "") -> CompiledStrategy:
    """
    Compile an expression AST into bytecode.
    Only the exact node types produced by GeneticStrategyEngine are supported.
    Deep or cyclic trees are rejected (CompileError).
    """
    consts: List[float] = []
    code = bytearray()
    n_ops = 0
    depth = [0]
    MAX_COMPILE_DEPTH = 128

    def add_const(v: float) -> int:
        for i, c in enumerate(consts):
            if abs(c - v) < 1e-12:
                return i
        if len(consts) >= 256:
            raise CompileError("too many constants")
        consts.append(float(v))
        return len(consts) - 1

    def compile_node(node: ast.AST):
        depth[0] += 1
        if depth[0] > MAX_COMPILE_DEPTH:
            raise CompileError(f"AST too deep (>{MAX_COMPILE_DEPTH})")
        try:
            if isinstance(node, ast.Constant):
                idx = add_const(float(node.value))
                code.extend(_emit(Op.PUSH_CONST, idx))
                nonlocal_ops()
            elif isinstance(node, ast.Name):
                if node.id not in FEATURE_INDEX:
                    raise CompileError(f"unknown feature: {node.id}")
                code.extend(_emit(Op.PUSH_FEAT, FEATURE_INDEX[node.id]))
                nonlocal_ops()
            elif isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    raise CompileError("only simple function calls allowed")
                fname = node.func.id
                if fname not in FUNC_TO_OP:
                    raise CompileError(f"unknown function: {fname}")
                for arg in node.args:
                    compile_node(arg)
                code.extend(_emit(FUNC_TO_OP[fname], 0))
                nonlocal_ops()
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                compile_node(node.operand)
                code.extend(_emit(Op.NEG, 0))
                nonlocal_ops()
            elif isinstance(node, ast.BinOp):
                compile_node(node.left)
                compile_node(node.right)
                if isinstance(node.op, ast.Add):
                    code.extend(_emit(Op.ADD, 0))
                elif isinstance(node.op, ast.Sub):
                    code.extend(_emit(Op.SUB, 0))
                elif isinstance(node.op, ast.Mult):
                    code.extend(_emit(Op.MUL, 0))
                elif isinstance(node.op, ast.Div):
                    code.extend(_emit(Op.DIV, 0))
                else:
                    raise CompileError(f"unsupported BinOp: {type(node.op)}")
                nonlocal_ops()
            else:
                raise CompileError(f"unsupported AST node: {type(node).__name__}")
        finally:
            depth[0] -= 1

    def nonlocal_ops():
        nonlocal n_ops
        n_ops += 1

    try:
        compile_node(tree)
    except RecursionError:
        raise CompileError("AST too deep or cyclic (RecursionError)")

    code.extend(_emit(Op.RET, 0))
    n_ops += 1

    if n_ops > 4096:
        raise CompileError(f"bytecode too large ({n_ops} ops)")

    return CompiledStrategy(
        code=bytes(code),
        consts=consts,
        source=source or "<compiled>",
        complexity=n_ops,
        n_ops=n_ops,
    )



def disassemble(cs: CompiledStrategy) -> str:
    """Human-readable disassembly for debugging."""
    lines = []
    i = 0
    code = cs.code
    while i < len(code):
        op_val, arg = struct.unpack_from("<BH", code, i)
        i += 3
        name = OP_NAMES.get(op_val, f"???{op_val}")
        if op_val == Op.PUSH_CONST:
            val = cs.consts[arg] if arg < len(cs.consts) else "?"
            lines.append(f"  {name:<12} {arg}  ({val})")
        elif op_val == Op.PUSH_FEAT:
            # reverse lookup
            feat = next((k for k, v in FEATURE_INDEX.items() if v == arg), str(arg))
            lines.append(f"  {name:<12} {arg}  ({feat})")
        else:
            lines.append(f"  {name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fuel-metered VM
# ---------------------------------------------------------------------------

class VMError(Exception):
    pass


class FuelExhausted(VMError):
    pass


class StackOverflow(VMError):
    pass


class StackUnderflow(VMError):
    pass


# Hard limits — these are the containment quotas
MAX_STACK   = 64
MAX_FUEL    = 2_048          # instructions per evaluation (generous for depth-6 trees)
MAX_CONSTS  = 64


def execute(
    cs: CompiledStrategy,
    features: Sequence[float],
    max_fuel: int = MAX_FUEL,
    max_stack: int = MAX_STACK,
) -> float:
    """
    Execute a compiled strategy against a feature vector.
    Returns a single float signal. Raises on any violation of quotas.
    """
    if len(features) < len(FEATURE_INDEX):
        raise VMError(f"feature vector too short (need {len(FEATURE_INDEX)}, got {len(features)})")

    stack: List[float] = []
    fuel = max_fuel
    code = cs.code
    consts = cs.consts
    ip = 0
    n = len(code)

    def push(v: float):
        if len(stack) >= max_stack:
            raise StackOverflow("strategy stack overflow")
        stack.append(v)

    def pop() -> float:
        if not stack:
            raise StackUnderflow("strategy stack underflow")
        return stack.pop()

    def safe_div(a: float, b: float) -> float:
        if abs(b) < 1e-12:
            return 0.0
        return a / b

    def safe_log(x: float) -> float:
        return math.log(max(x, 1e-12))

    def safe_exp(x: float) -> float:
        return math.exp(min(max(x, -20.0), 20.0))

    def clip(x: float) -> float:
        return max(-1.0, min(1.0, x))

    while ip < n:
        if fuel <= 0:
            raise FuelExhausted("strategy exceeded instruction fuel limit")
        fuel -= 1

        op_val, arg = struct.unpack_from("<BH", code, ip)
        ip += 3

        if op_val == Op.PUSH_CONST:
            push(consts[arg])
        elif op_val == Op.PUSH_FEAT:
            push(float(features[arg]))
        elif op_val == Op.NEG:
            push(-pop())
        elif op_val == Op.ABS:
            push(abs(pop()))
        elif op_val == Op.LOG:
            push(safe_log(pop()))
        elif op_val == Op.EXP:
            push(safe_exp(pop()))
        elif op_val == Op.CLIP:
            push(clip(pop()))
        elif op_val == Op.SIGN:
            x = pop()
            push(1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
        elif op_val == Op.ADD:
            b, a = pop(), pop()
            push(a + b)
        elif op_val == Op.SUB:
            b, a = pop(), pop()
            push(a - b)
        elif op_val == Op.MUL:
            b, a = pop(), pop()
            push(a * b)
        elif op_val == Op.DIV:
            b, a = pop(), pop()
            push(safe_div(a, b))
        elif op_val == Op.MAX:
            b, a = pop(), pop()
            push(max(a, b))
        elif op_val == Op.MIN:
            b, a = pop(), pop()
            push(min(a, b))
        elif op_val == Op.GT:
            b, a = pop(), pop()
            push(1.0 if a > b else 0.0)
        elif op_val == Op.LT:
            b, a = pop(), pop()
            push(1.0 if a < b else 0.0)
        elif op_val == Op.IF_ELSE:
            # stack: [cond, then, else]  (else is top)
            else_v = pop()
            then_v = pop()
            cond = pop()
            push(then_v if cond > 0.5 else else_v)
        elif op_val == Op.RET:
            if not stack:
                return 0.0
            return float(stack[-1])
        else:
            raise VMError(f"unknown opcode {op_val}")

    # fell off the end without RET
    return float(stack[-1]) if stack else 0.0


# ---------------------------------------------------------------------------
# Convenience: compile + run in one call
# ---------------------------------------------------------------------------

def run_strategy(tree: ast.AST, features: Sequence[float], source: str = "") -> Tuple[float, CompiledStrategy]:
    cs = compile_ast(tree, source)
    signal = execute(cs, features)
    return signal, cs
