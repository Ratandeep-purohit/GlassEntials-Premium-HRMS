import ast
import operator as op
from decimal import Decimal, InvalidOperation

class FormulaError(Exception):
    """Custom exception for payroll formula errors."""
    pass

class SafeFormulaRunner:
    """
    A safe mathematical expression evaluator for payroll formulas.
    Uses Python's AST (Abstract Syntax Tree) to parse and evaluate 
    expressions without using eval().
    """

    # Supported operators
    OPERATORS = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Pow: op.pow,
        ast.USub: op.neg,
    }

    def __init__(self, variables=None):
        """
        :param variables: Dict of variable names and their Decimal values.
                          Example: {'basic': Decimal('50000'), 'gross': Decimal('70000')}
        """
        self.variables = variables or {}
        # Ensure all variables are Decimals for precision
        for k, v in self.variables.items():
            if not isinstance(v, Decimal):
                try:
                    self.variables[k] = Decimal(str(v))
                except (InvalidOperation, ValueError):
                    self.variables[k] = Decimal("0.00")

    def evaluate(self, expression):
        """
        Parses and evaluates the expression.
        Returns a Decimal.
        """
        if not expression or not expression.strip():
            return Decimal("0.00")

        try:
            tree = ast.parse(expression.strip(), mode='eval')
            result = self._eval_node(tree.body)
            return Decimal(str(result)).quantize(Decimal("0.01"))
        except ZeroDivisionError:
            raise FormulaError(f"Division by zero in formula: {expression}")
        except KeyError as e:
            raise FormulaError(f"Undefined variable or operator {e} in formula: {expression}")
        except Exception as e:
            raise FormulaError(f"Error evaluating formula '{expression}': {str(e)}")

    def _eval_node(self, node):
        """Recursive helper to evaluate AST nodes."""
        
        # Numbers: 100, 20.5
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return Decimal(str(node.value))
            return node.value

        # Variables: basic, gross
        elif isinstance(node, ast.Name):
            if node.id in self.variables:
                return self.variables[node.id]
            raise FormulaError(f"Variable '{node.id}' is not allowed or defined.")

        # Binary Ops: basic * 0.12
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self.OPERATORS[type(node.op)](left, right)

        # Unary Ops: -basic
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            return self.OPERATORS[type(node.op)](operand)

        # Parentheses are handled automatically by the AST structure (BinOp hierarchy)
        
        else:
            raise FormulaError(f"Unsupported syntax: {type(node).__name__}")

def evaluate_formula(formula, context):
    """
    Convenience function to evaluate a formula with a given context.
    :param formula: String expression.
    :param context: Dict of variables.
    """
    runner = SafeFormulaRunner(context)
    return runner.evaluate(formula)
