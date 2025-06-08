import hexaly.optimizer
import sys
from math import sqrt
from BaseMath import *

def build_model():
    with hexaly.optimizer.HexalyOptimizer() as optimizer:
        #
        # Declare the optimization model
        #
        nP = 4

        # Plate (global) and platform (local) split_index sets
        IG = range(nP + 1) # Plates
        IL = range(nP) # Platforms
        J = range(6) # Legs
        K = range(3) # Spatial dimensions

        # Data input. Stubs for now.
        pL_rest = [[0,0,1] for i in IL]
        pL_leg_attachments = [[[1, 1, 1] for j in J] for i in IG]
        pl_leg_vectors_rest = [[[1, 1, 1] for j in J] for i in IL]

        m = optimizer.model

        # Numerical decisions

        pG = [Vector([n.float() for k in K]) for i in IG]

        Rx = [Vector([m.float() for k in K]) for i in IG]
        Ry = [Vector([m.float() for k in K]) for i in IG]
        Rz = [Rx[i].cross(Ry[i]) for i in IG]

        RG = Matrix([Rx, Ry, Rz]).transpose()

        # Constraints: define rotation matrix
        Rx_norm1 = [m.contstraint(Rx[i].normsq() == 1) for i in IG]
        Ry_norm1 = [m.contstraint(Ry[i].normsq() == 1) for i in IG]
        Rx_Ry_orth = [m.contstraint(Rx[i].dot(Ry[i]) == 0) for i in IG]

        # Note: This way of doing the cross product gives you a proper rotation matrix. Negate it, and it will rotate and reflect

        # Bottom plate fixing: p=0, R=I
        bottom_pos = [m.constraint(pG[0][k] == 0) for k in K]
        bottom_rot = [m.constraint(RG[0][k][l] == (k==l) for k in K for l in K)]

        # Local rotations/positions
        RL = [RG[i].transpose()*RG[i+1] for i in IL]
        pL = [RG[i].transpose()*(pG[i+1]-pG[i]) for i in IL]

        # Leg attachment locations
        pL_leg_lower = [RL[i] for i in IL]

    """
        # Surface must not exceed the surface of the plain disc
        surface = PI * r ** 2 + PI * (R + r) * m.sqrt((R - r) ** 2 + h ** 2)
        m.constraint(surface <= PI)

        # Maximize the volume
        volume = PI * h / 3 * (R ** 2 + R * r + r ** 2)
        m.maximize(volume)

        m.close()

        #
        # Parametrize the optimizer
        #
        if len(sys.argv) >= 3:
            optimizer.param.time_limit = int(sys.argv[2])
        else:
            optimizer.param.time_limit = 2

        optimizer.solve()

        #
        # Write the solution in a file with the following format:
        #  - surface and volume of the bucket
        #  - values of R, r and h
        #
        if len(sys.argv) >= 2:
            with open(sys.argv[1], 'w') as f:
                f.write("%f %f\n" % (surface.value, volume.value))
                f.write("%f %f %f\n" % (R.value, r.value, h.value))
    """