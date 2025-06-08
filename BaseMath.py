import hexaly.optimizer
import sys
from math import sqrt


I = lambda n : Matrix([[i==j for j in range(n)] for i in range(n)])
norm = lambda m,r : m.sqrt(normsq(r))
normsq = lambda r : sum(ri*ri for ri in r)

class Matrix:
    def __init__(self, matrix):
        self.matrix = matrix
        self.rows = len(matrix)
        self.cols = len(matrix[0])

    def __repr__(self):
        return ('[' +
                '\n '.join(
                    ', '.join(str(mij) for mij in row)
                    for row in self.matrix)
                + ']')

    def __getitem__(self, item):
        return self.matrix[item]

    def __iter__(self):
        return self.matrix.__iter__()

    def __len__(self):
        return self.matrix.__len__()


    def __add__(self, other):
        # Add via matrix addition.
        if not isinstance(other, Matrix):
            raise TypeError(f"Matrix must be of type Matrix, not {type(other)}")
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrix must have the same number of rows and columns")

        return Matrix([[x1 + other[i][j] for (j,x1) in enumerate(row) ] for (i,row) in enumerate(self)])

    def __sub__(self, other):
        if not isinstance(other, Matrix):
            raise TypeError(f"Matrix must be of type Matrix, not {type(other)}")
        if self.rows != other.rows or self.cols != other.cols:
            raise ValueError("Matrices must have the same number of rows and columns")

        return Matrix([[x1 - other[i][j] for (j,x1) in enumerate(row) ] for (i,row) in enumerate(self)])

    def __mul__(self, other):
        if isinstance(other, Matrix):
            return self.matrix_multiply(other)
        else: # Assume it's a scalar of some form - such as a double or Hexaly variable.
            return self.scalar_multiply(other)

    def __truediv__(self, scalar):
        if isinstance(scalar, Matrix):
            raise NotImplementedError("Linear solves with Hexaly variables are not supported")
        if scalar == 0:
            raise ValueError("Cannot divide by zero")
        return self.scalar_multiply(1/scalar)

    def __rmul__(self, other):
        return self.scalar_multiply(other)

    def matrix_multiply(self, other):
        if not (self.cols == other.rows):
            raise ValueError(
                f"Matrix dimensions {self.rows}x{self.cols} and {other.rows}x{other.cols} are incompatible for multiplication.")

        return Matrix(
            [[sum(self[i][k] * other[k][j] for k in range(self.cols)) for j in range(other.cols)]
             for i in range(self.rows)])

    def scalar_multiply(self, scalar):
        return Matrix([[scalar * x for x in row] for row in self])

    def flatten(self):
        return Vector([m for row in self for m in row])

    def dim(self):
        return self.rows, self.cols

    def transpose(self):
        (m, n) = self.dim()
        return Matrix([[self[i][j] for i in range(m)] for j in range(n)])

    def normFsq(self):
        return sum(mij**2 for row in self for mij in row)

    def normF(self):
        return sqrt(self.normFsq())

    def normF_hex(self, m):
        return m.sqrt(self.normFsq())

class Vector(Matrix):
    def __init__(self, v):
        # Input is a flat list/enumerable
        super().__init__([[vi] for vi in v])
        self.v = self.matrix

    def __repr__(self):
        lst = self.to_list()
        if self.rows == 1:
            # Row vector - first element is whole vector, but transposed from default
            return f"[{', '.join(str(vi) for vi in lst)}]^T"
        else:
            # Column vector - first element of transpose is whole vector. Default shape
            return f"Vector[{', '.join(str(vi) for vi in lst)}]"

    def dot(self, other):
        if not isinstance(other, Vector):
            raise TypeError(f"Vector must be of type Vector, not {type(other)}")
        return sum(vi*other[i] for (i,vi) in enumerate(self))

    def cross(self, other):
        # Cross product, 3D only for now. (Other dimensions require d-1 vectors for their cross product analogue,
        # where d is the dimension. And they require  subdeterminant calculations - which are too involved for now)
        if not isinstance(other, Vector):
            raise TypeError(f"Vector must be of type Vector, not {type(other)}")

        if len(self) != 3 or len(other) != 3:
            raise ValueError(f"Vectors must have 3 elements, not {len(self)} and {len(other)}. May change this later.")

        # Cross product between self and other
        return cpo(self.v)*other

    def to_list(self):
        if self.rows == 1:
            return list(self[0])
        else:
            return list(self.transpose()[0])

    def normsq(self):
        return normsq(self.to_list())

    def norm_hex(self, m):
        # Norm using Hexaly model. Needed to get right sqrt
        return norm(m, self.to_list())

    def norm(self):
        # Numeric norm
        return sqrt(self.normsq())

    # Note: vectors are horizontal by default. However: the transpose of a horizontal vector is a vertical vector. Both flatten to a vertical vector

#mat = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
#print(mat)
#print(mat.flatten())
#print(mat.transpose().flatten())


def getR(m, r):
    #For initialization only, not Hexaly variables. I used the matrices as variables in the paper - a stroke of brilliance
    normr = norm(m,r)
    if normr < 1e-6:
        return I3

    cpo_r = cpo(r)
    return I3 + m.sin(normr)*cpo_r/normr + (1-m.cos(normr))*cpo_r*cpo_r/(normr*normr)

I3 = I(3)

def cross_product_operator(vec3):
    # Vec3 must have 3 components. Can be a Vector
    if not len(vec3) == 3:
        raise ValueError(f"Vector must have 3 elements, not {len(vec3)}")

    return Matrix([[0, -vec3[2], vec3[1]],
                [vec3[2], 0, -vec3[0]],
                [-vec3[1], vec3[0], 0]])

cpo = cross_product_operator

def space_transformation_matrix(p: list, r: list):
    cpo = cross_product_operator(r)
