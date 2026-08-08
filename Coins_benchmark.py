from functools import lru_cache
from math import gcd, lcm, sqrt
from collections import defaultdict
import time
import sys
from xml.dom.domreg import well_known_implementations

NS = float('inf')
SKIP = -1


class Solution:
    def coinChangeDP(self, coins, amount):
        if amount == 0:
            return 0
        coins.sort(reverse=True)

        self.n = len(coins)
        self.coins = coins

        # Track depth and bestDepth globally so as not to interfere with core memoization
        # self.depth = 0 #Coins used so far at current branch
        # self.bestDepth = ns #Best solution so far
        self.enterCount = 0
        self.exploreCount = 0

        result = self.coinChangeHelperDP(amount)

        self.coinChangeHelperDP.cache_clear()

        print(
            f"enterCount={self.enterCount}, exploreCount={self.exploreCount}")
        print(f"best depth:{result}")

        return -1 if result == NS else result

    @lru_cache(maxsize=None)
    def coinChangeHelperDP(self, amount):
        # self.depth += 1

        # if amount == 0:
        #    self.bestDepth = self.depth
        #    self.depth -= 1
        #    return 0
        # if amount < 0:
        #    return ns

        # if self.depth == self.bestDepth - 1:
        # prune immediately! We've already solved the master problem using 1 extra coin.
        #    self.depth -= 1
        #    return ns

        self.exploreCount+=1
        minSln = NS
        for coin in self.coins:
            if coin > amount:
                continue

            if coin == amount:
                minSln = 1
                # self.bestDepth = self.depth
                break

            self.enterCount += 1
            minSln = min(minSln, 1 + self.coinChangeHelperDP(amount - coin))

        # self.depth -= 1
        return minSln


    def coinChangeBranch(self, coins, amount):
        if amount == 0:
            return 0
        coins.sort(reverse=True)
        # revCumGCDs = list(coins)
        # revCumGCDs[-1] = coins[-1]
        # for j in range(len(coins)-2, -1, -1):
        #    revCumGCDs[j] = gcd(coins[j], revCumGCDs[j+1])

        # print(coins)
        # print(revCumGCDs)

        self.coins = coins
        self.coinsSet = set(coins)
        n = len(coins)
        self.minCoin = min(coins)

        revGCD = coins.copy()
        for i in range(n-2,-1,-1):
            revGCD[i]=gcd(coins[i], revGCD[i+1])
        self.revGCD = revGCD

        print(revGCD)
        # self.revCumGCDs = revCumGCDs

        # Track depth and bestDepth globally so as not to interfere with core memoization
        self.bestDepth = NS  # Best solution so far

        self.enterCount = 0
        self.exploreCount = 0

        # Stores best solution so far (or SKIP if none so far, or NS if proven impossible), largest depth budget, and smallest depth called from.
        # If a branch for some amount has already evaluated with a larger budget or smaller starting depth, there's no used to re-evaluating that amount.
        # An amount should only be re-evaluated if called earlier than ever before, with a larger depth budget than ever before, if not solved or proven infeasible.
        # In this case, there may be some previously skipped child branches to re-evaluate at greater depth.

        # Never enter helper if amount<0 to avoid collisions with SKIP.
        # If SLN>0, the depth budget may be unecessarily deep - but it won't matter, as it will shortcut in the logic because sln>0)
        self.cache = defaultdict( lambda: (SKIP, 0, NS))  # SLN= SKIP, never had any budget (0), never entered before (smallest depth = infty)
        result = self.coinChangeHelper(amount, 0, 0)

        # self.coinChangeHelper.cache_clear()
        print(
            f"enterCount={self.enterCount}, exploreCount={self.exploreCount}, firstExploreCount={len(self.cache)}, reExploreCount={self.exploreCount - len(self.cache)}")
        print(f"best depth:{self.bestDepth}")
        return -1 if result == NS else result

    # IMPOSSIBLE proof only occurs if ALL branches evaluate (not skip) with result IMPOSSIBLE, or all denominations are too large for the result.
    def coinChangeHelper(self, amount, depth, minIdToTryMax):
        # INVARIANTs:
        #   1) self.depth is "coins used so far before this branch". Base depth = 0.
        #   2) If a finite nonnegative solution is assigned in the cache, that solution is the best possible for amount.

        self.enterCount += 1

        # Slight optimization: prune early if no coin exists to help meet amount, or if it needs more than one, but less than 2, mincoin copies
        if amount != self.minCoin and amount < 2 * self.minCoin and amount not in self.coinsSet:
            return NS

        bestDepth = self.bestDepth
        depthBudget = bestDepth - depth

        (bestSln, largestBudget, shortestDepth) = self.cache[amount]

        # print(f"\nEvaluating amount {amount} at depth {depth} with bestDepth {bestDepth}, budget {depthBudget}."+
        #      f" bestSln={bestSln}, largestBudget={largestBudget}, shortestDepth={shortestDepth}")
        if bestSln == NS:
            # print("Detected infeasible. Returning.")
            # Previously proven unsolvable! Return unsolvable
            return NS

        if depth >= shortestDepth:
            # print("We've visited from weakly shallower! Skip")
            # We've already visited here from a shorter (or equal) depth! Skip
            return SKIP

        if bestSln > SKIP:
            # Huzzah! We've reached a solved branch faster than ever before. Update current best depth, and update that we reached it with a tighter budget.
            # But there might be better solved branches(?). Update this branch, and continue
            if bestSln + depth < self.bestDepth:
                self.bestDepth = bestSln + depth
            # print(f"We already have solution {bestSln}! Update with improved entry depth {bestSln}, budget {depthBudget}, and total depth {self.bestDepth}")

            newLargestBudget = max(largestBudget, depthBudget)
            self.cache[amount] = (bestSln, newLargestBudget, depth)
            return bestSln

        if depthBudget <= largestBudget:
            #    print("We've visited with a weakly larget budget! Skip")
            # We can't make progress by branching here: we've already branched as deep as matters from here.
            return SKIP

        self.exploreCount += 1
        minCost = NS
        canProveImpossible = True
        for (i, coin) in enumerate(self.coins):
            if coin > amount:
                continue

            if amount%self.revGCD[i]:
                # Cannot build amount with the coins remaining
                #print(f"GCD prune! Coin={coin}, cID={cID}")
                break

            maxNumCoin = amount // coin

            if amount % coin == 0:
                # This is a "mark solved in cache" branch. We have a unique optimum for amount.
                maxNumCoin = amount // coin
                minCost = min(minCost, maxNumCoin)
                # print(f"Found shortcut solution for {amount}! Coin={coin}, nCoin={nCoin}, depth={depth}, minCost={minCost}, totalCost={nCoin+depth}, bestCost={self.bestDepth}")
                break

            if min(depth + 2, depth + maxNumCoin + 1) >= self.bestDepth:
                # Since coins are decreasing, and the current coin can't solve the problem directly, we need at least 2 more coins to solve it.
                # If we already have a solution using 2 more coins, there's no use branching further.
                # Likewise, if using only copies of the current coin would take more coins than the best solution so far, then the same will
                # be the case for all future coins. So we break. Note at this point that amount//coin>0, so we would need "all this coin, then another coin" - so we add 1 to depth+amount//coin.
                #    print(f"Cannot improve: depth={depth}, maxCoins = {amount//coin+1}, bestDepth={self.bestDepth}")
                canProveImpossible = False
                break

            # mygcd = self.revCumGCDs[cID]
            # if amount % mygcd != 0:
            # Remaining coins can't be used to reach target due to incompatible gcd! Break.
            # print(f"Wow it actually happened with cID={cID}, amount={amount}, gcd={mygcd}.")
            # canProveImpossible = False
            #    break

            # Branch, check for SKIP, determine the new MinCost, ensuring that SKIP never makes it into minCost.
            if maxNumCoin > 1 and i >= minIdToTryMax:
                #while maxNumCoin > 1:
                    #print(f"Trying {maxNumCoin} number of {coin}.")
                    # Branch, check for SKIP, determine the new MinCost, ensuring that SKIP never makes it into minCost.
                nextCost = self.coinChangeHelper(amount-maxNumCoin*coin, depth+maxNumCoin, i+1)
                if nextCost == SKIP:
                    #print(f"Result after trying {maxNumCoin} number of {coin}: SKIP.")
                    canProveImpossible = False
                elif nextCost != NS:
                    minCost = min(minCost, nextCost+maxNumCoin)
                        #print(f"Result after trying {maxNumCoin} number of {coin}: minCost={minCost}, bestDepth={self.bestDepth}.")
                        # print(f"Amount {amount}: Updating minCost to {minCost} from branch with coin {coin}")

                    #maxNumCoin //= 2

            #if min(depth + 2, depth + maxNumCoin + 1) >= self.bestDepth:
                # Since coins are decreasing, and the current coin can't solve the problem directly, we need at least 2 more coins to solve it.
                # If we already have a solution using 2 more coins, there's no use branching further.
                # Likewise, if using only copies of the current coin would take more coins than the best solution so far, then the same will
                # be the case for all future coins. So we break. Note at this point that amount//coin>0, so we would need "all this coin, then another coin" - so we add 1 to depth+amount//coin.
                #    print(f"Cannot improve: depth={depth}, maxCoins = {amount//coin+1}, bestDepth={self.bestDepth}")
            #    canProveImpossible = False
            #    break

            # Branch, check for SKIP, determine the new MinCost, ensuring that SKIP never makes it into minCost.
            nextCost = self.coinChangeHelper(amount-coin, depth+1, minIdToTryMax)
            if nextCost == SKIP:
                canProveImpossible = False
            elif nextCost != NS:
                minCost = min(minCost, nextCost+1)
                # print(f"Amount {amount}: Updating minCost to {minCost} from branch with coin {coin}")

        # If we found something: MinCost will be >SKIP! In this case we'll store it along with the budget.
        # Note: the budget will only have shifted if we found a solution (the best for the branch). In this case, we simply don't give a hoot since the \
        #   logic will be dominated by the fact that we found a solution.
        if minCost != NS:
            newCost = depth + minCost
            if (newCost < self.bestDepth):
                # print(f"New best depth of {newCost} detected!")
                self.bestDepth = min(self.bestDepth, newCost)

        if minCost == NS and not canProveImpossible:
            # Didn't find a better solution, but skipped over some stuff.
            minCost = SKIP

        # Update cache
        self.cache[amount] = (minCost, depthBudget, depth)

        # print(f"Min-cost for branch {amount} with depth {depth} and budget {depthBudget} is {minCost}")
        return minCost

    def coinChangeBranchWithOrderedSearch(self, coins, amount, useCanonicity = False, useWeakCanonicity = False, useSylvesterStabilityBounds = False, useBFSStabilityBounds = False):
        if amount == 0:
            return 0
        coins.sort(reverse=True)

        while len(coins)>0 and amount < coins[0]:
            coins.pop(0)

        if not coins:
            return -1
        # revCumGCDs = list(coins)
        # revCumGCDs[-1] = coins[-1]
        # for j in range(len(coins)-2, -1, -1):
        #    revCumGCDs[j] = gcd(coins[j], revCumGCDs[j+1])
        # print(coins)
        # print(revCumGCDs)

        self.coins = coins
        self.coinsSet = set(coins)
        n = len(coins)
        self.n = n
        self.minCoin = min(coins)


        revGCD = coins.copy()
        for i in range(n-2,-1,-1):
            revGCD[i]=gcd(coins[i], revGCD[i+1])
        self.revGCD = revGCD

        print(f"revGCD = {revGCD}")
        self.useCanonicity = useCanonicity
        self.globalCache = {}  # Form is (amount, minID) : optimum. No SKIP possibility - since it's branch-incognizant.
        if useCanonicity:
            self.build_rev_is_canonical(amount, useWeakCanonicity)
            print(f"isCanonical = {self.isWeaklyCanonical}")

            if self.isCanonical[0]:
                # We're canonical! Turn the dest_route stuff off baby, time to get greedy!
                useSylvesterStabilityBounds = False
                useBFSStabilityBounds = False

        useSylvesterStabilityBounds = useSylvesterStabilityBounds and n >= 2
        if useSylvesterStabilityBounds:
            sylvesterBounds = coins.copy()
            sylvesterBounds[-1]=NS
            sylvesterBounds[-2]=NS
            for i in range(n - 3):
                c0=coins[i]
                c1=coins[i+1]
                g = revGCD[i]
                sylvesterBounds[i] = c1*(c0-g)/g

                # Instantly choose chosen until amount < sylvester!
                # Equivalently: Choose (amount-sylvester)//coins[0] of max immediately
                # print(f"Sylvester bounds took amount down to {amount} by pre-choosing {preChosen} {coins[0]}'s!")
            # Sylvester number for smallest is just smallest lol
            sylvesterBounds[-1] = NS
            self.sylvesterBounds = sylvesterBounds
            print(f"Sylvester stability Bounds: {sylvesterBounds}")

        self.useSylvesterStabilityBounds = useSylvesterStabilityBounds

        useBFSStabilityBounds = useBFSStabilityBounds and  n>=3
        if useBFSStabilityBounds:
            self.makeRemainderBasedStableBounds(amount)
            print(f"Number remainders cached in remainder based stable bounds: {sum(len(self.remainderBasedStableBounds[lookup][0]) for lookup in self.remainderBasedStableBounds)}")

            print(f"BFS Stability bounds: {[max(self.remainderBasedStableBounds[tailID][0].values())[0] for tailID in range(n-2) if tailID in self.remainderBasedStableBounds]}")
            print(f"BFS Stability completes: {[self.remainderBasedStableBounds[tailID][1] for tailID in range(n-2) if tailID in self.remainderBasedStableBounds]}")
            for (key, (lookup, isComplete)) in self.remainderBasedStableBounds.items():
                completeStr = "complete" if isComplete else "incomplete"
               # print(f"Worst (amount, depth) for {completeStr} tail {key}: {max(lookup.values())}")
                #print(f"Mean (amount, depth) for {completeStr} tail {key}: {sum(val[0] for val in lookup.values())/len(lookup)}")

        self.useBFSStabilityBounds = useBFSStabilityBounds



        # self.revCumGCDs = revCumGCDs

        # Track depth and bestDepth globally so as not to interfere with core memoization
        self.bestDepth = self.greedy_solve(amount, 0)  # Best solution so far

        self.enterCount = 0
        self.exploreCount = 0

        # Stores best solution so far (or SKIP if none so far, or NS if proven impossible), largest depth budget, and smallest depth called from.
        # If a branch for some amount has already evaluated with a larger budget or smaller starting depth, there's no used to re-evaluating that amount.
        # An amount should only be re-evaluated if called earlier than ever before, with a larger depth budget than ever before, if not solved or proven infeasible.
        # In this case, there may be some previously skipped child branches to re-evaluate at greater depth.

        # Never enter helper if amount<0 to avoid collisions with SKIP.
        # If SLN>0, the depth budget may be unecessarily deep - but it won't matter, as it will shortcut in the logic because sln>0)
        self.cache = defaultdict( lambda: (SKIP, 0, NS, 0))  # SLN= SKIP, never had any budget (0), never entered before (smallest depth = infty)

        # Global cache incognizant of original amount, caring only about current amount. Just (amount, minID) with no overwriting based on branch etc.
        self.globalCache = {} # Form is (amount, minID) : optimum. No SKIP possibility - since it's branch-incognizant.

        self.coinChangeBranchWithOrderedSearchHelper(amount, depth=0, minCoinId=0, canCheckMinIdForMax = True)
        result = self.bestDepth

        # self.coinChangeHelper.cache_clear()
        print(
            f"enterCount={self.enterCount}, exploreCount={self.exploreCount}, firstExploreCount={len(self.cache)}, reExploreCount={self.exploreCount - len(self.cache)}")
        print(f"best depth:{self.bestDepth}")
        return -1 if result == NS else result

    # IMPOSSIBLE proof only occurs if ALL branches evaluate (not skip) with result IMPOSSIBLE, or all denominations are too large for the result.
    def coinChangeBranchWithOrderedSearchHelper(self, amount, depth, minCoinId, canCheckMinIdForMax):
        # INVARIANTs:
        #   1) self.depth is "coins used so far before this branch". Base depth = 0.
        #   2) If a finite nonnegative solution is assigned in the cache, that solution is the best possible for amount.

        self.enterCount += 1
        #if amount < 10000:
            # Just use DP. Don't bother updating current cache - will only hit DP cache for these cases.
        #    return self.coinChangeHelperDP(amount)

        # Slight optimization: prune early if no coin exists to help meet amount, or if it needs more than one, but less than 2, mincoin copies
        #if amount != self.minCoin and amount < 2 * self.minCoin and amount not in self.coinsSet:
        #    if(amount, minCoinId) not in self.globalCache:
        #        self.globalCache[amount, minCoinId] = NS
        #    return NS

        bestDepth = self.bestDepth
        depthBudget = bestDepth - depth

        (bestSln, largestBudget, shortestDepth, cachedMinCoinId) = self.cache[amount]

        if (amount, minCoinId) in self.globalCache:
            # It's solved!
            self.cache[amount] = (self.globalCache[amount, minCoinId], max(depthBudget, largestBudget), min(depth, shortestDepth), min(minCoinId, cachedMinCoinId))
            return self.globalCache[amount, minCoinId]

        # print(f"\nEvaluating amount {amount} at depth {depth} with bestDepth {bestDepth}, budget {depthBudget}."+
        #      f" bestSln={bestSln}, largestBudget={largestBudget}, shortestDepth={shortestDepth}")
        if(minCoinId >= cachedMinCoinId): # May not need to re-explore: we have fewer options than before!
            if bestSln == NS:
                # print("Detected infeasible. Returning.")
                # Previously proven unsolvable! Return unsolvable
                return NS

            if depth >= shortestDepth:
                # print("We've visited from weakly shallower! Skip")
                # We've already visited here from a shorter (or equal) depth! Skip
                return SKIP

            if bestSln > SKIP:
                # Huzzah! We've reached a solved branch faster than ever before. Update current best depth, and update that we reached it with a tighter budget.
                # But there might be better solved branches(?). Update this branch, and continue
                if bestSln + depth < self.bestDepth:
                    self.bestDepth = bestSln + depth
                # print(f"We already have solution {bestSln}! Update with improved entry depth {bestSln}, budget {depthBudget}, and total depth {self.bestDepth}")

                newLargestBudget = max(largestBudget, depthBudget)
                self.cache[amount] = (bestSln, newLargestBudget, depth, cachedMinCoinId)

                # CANNOT put bestSln in global cache here: amount is optimal for the amount given that we're using
                # SOME SUBSET of the coins with index >=cachedMinCoinID. BUT the optimal for the last
                # minCoinID may be, and usually will be, worse.

                return bestSln

            if depthBudget <= largestBudget:
                #    print("We've visited with a weakly larget budget! Skip")
                # We can't make progress by branching here: we've already branched as deep as matters from here.
                return SKIP

        self.exploreCount += 1
        minCost = NS
        canProveImpossible = True
        nextCost = NS

        def updateMinCost(offset):
            nonlocal canProveImpossible, minCost
            if nextCost == SKIP:
                canProveImpossible = False
            elif nextCost != NS:
                minCost = min(minCost, nextCost+offset)


        for i in range(minCoinId, self.n):
            coin = self.coins[i]
            if coin > amount:
                continue

            if i == self.n - 2:
                nextCost = self.solve2Coin(amount)

            #    verify = self.coinChange2DDP(amount, cID)
            #    if(nextCost != verify):
            #        print(f"2-coin results: amount={amount}, coin={coin}, coins[-1]={self.coins[-1]}, coins[-2]={self.coins[-2]}, cost={nextCost}, trueCost={verify}")
            #    else:
            #        print(f"2-coin results: amount={amount}, coin={coin}, coins[-1]={self.coins[-1]}, coins[-2]={self.coins[-2]}, cost={nextCost}, trueCost=RIGHT!!!!!!")

                self.globalCache[amount, i] = nextCost
                minCost = min(minCost, nextCost)
                break

            if self.useBFSStabilityBounds and i in self.remainderBasedStableBounds:
                (lookups, isComplete) = self.remainderBasedStableBounds[i]
                remainder = amount % coin

                if remainder in lookups:
                    # Lookup best number for this remainder, and branch. Guaranteed optimal for the tail since it's in lookups.
                    (lookupAmt, lookupDepth) = lookups[remainder]

                    if amount >= lookupAmt + coin: # We can improve by subtracting!
                        # If this statement is false, then amount is too small to use our BFS results:
                        # It may take more coins to reach the same remainder with smaller amounts.
                        preChosen = (amount - lookupAmt)//coin

                        minCost = min(minCost, lookupDepth + preChosen)
                        if isComplete:
                            break
                        #print(f"Remainder={remainder}, lookups[remainder]={lookups[remainder]}, amount={amount}, coin={coin}, "
                              #f"preChosen={preChosen}, nextCost={lookupDepth + preChosen}, minCost={minCost}, depth={depth}")
                    # We can gas to remainder without going past it!

                elif isComplete:
                    # It's not in lookups - therefore there's no solution! Break
                    break

            if self.useSylvesterStabilityBounds:
                sylvester = self.sylvesterBounds[i]
                if amount - sylvester >= coin:
                    preChosen = max(0,int(amount-self.sylvesterBounds[i])//coin)
                    nextCost = self.coinChangeBranchWithOrderedSearchHelper(amount - coin*preChosen, depth+preChosen, minCoinId=i, canCheckMinIdForMax=True)
                    updateMinCost(preChosen)
                    break

            if amount%self.revGCD[i]:
                # Cannot build amount with the coins remaining
                #print(f"GCD prune! Coin={coin}, cID={cID}")
                break

            if self.useCanonicity and self.isWeaklyCanonical[i]:
                # Can do greedy search!
                greedySln = self.greedy_solve(amount, i)
                if greedySln != NS:
                    minCost = min(minCost, greedySln)
                    break

            maxNumCoin = amount // coin

            if amount % coin == 0:
                # This is a "mark solved in cache" branch. We have a unique optimum for amount.
                maxNumCoin = amount // coin
                minCost = min(minCost, maxNumCoin)
                # print(f"Found shortcut solution for {amount}! Coin={coin}, nCoin={nCoin}, depth={depth}, minCost={minCost}, totalCost={nCoin+depth}, bestCost={self.bestDepth}")
                break

            if min(depth + 2, depth + maxNumCoin + 1) >= self.bestDepth:
                # Since coins are decreasing, and the current coin can't solve the problem directly, we need at least 2 more coins to solve it.
                # If we already have a solution using 2 more coins, there's no use branching further.
                # Likewise, if using only copies of the current coin would take more coins than the best solution so far, then the same will
                # be the case for all future coins. So we break. Note at this point that amount//coin>0, so we would need "all this coin, then another coin" - so we add 1 to depth+amount//coin.
                #    print(f"Cannot improve: depth={depth}, maxCoins = {amount//coin+1}, bestDepth={self.bestDepth}")
                canProveImpossible = False
                break

            # mygcd = self.revCumGCDs[cID]
            # if amount % mygcd != 0:
            # Remaining coins can't be used to reach target due to incompatible gcd! Break.
            # print(f"Wow it actually happened with cID={cID}, amount={amount}, gcd={mygcd}.")
            # canProveImpossible = False
            #    break

            # Branch, check for SKIP, determine the new MinCost, ensuring that SKIP never makes it into minCost.

            if maxNumCoin > 1 and i >= minCoinId+1-canCheckMinIdForMax:
                # Branch, check for SKIP, determine the new MinCost, ensuring that SKIP never makes it into minCost.
                nextCost = self.coinChangeBranchWithOrderedSearchHelper(amount-maxNumCoin*coin, depth+maxNumCoin, minCoinId = i+1, canCheckMinIdForMax = True)
                updateMinCost(maxNumCoin)

            #if min(depth + 2, depth + maxNumCoin + 1) >= self.bestDepth:
                # Since coins are decreasing, and the current coin can't solve the problem directly, we need at least 2 more coins to solve it.
                # If we already have a solution using 2 more coins, there's no use branching further.
                # Likewise, if using only copies of the current coin would take more coins than the best solution so far, then the same will
                # be the case for all future coins. So we break. Note at this point that amount//coin>0, so we would need "all this coin, then another coin" - so we add 1 to depth+amount//coin.
                #    print(f"Cannot improve: depth={depth}, maxCoins = {amount//coin+1}, bestDepth={self.bestDepth}")
            #    canProveImpossible = False
            #    break

            # Branch, check for SKIP, determine the new MinCost, ensuring that SKIP never makes it into minCost.
            nextCost = self.coinChangeBranchWithOrderedSearchHelper(amount-coin, depth+1, minCoinId = i, canCheckMinIdForMax = False)
            updateMinCost(1)
                # print(f"Amount {amount}: Updating minCost to {minCost} from branch with coin {coin}")

        # If we found something: MinCost will be >SKIP! In this case we'll store it along with the budget.
        # Note: the budget will only have shifted if we found a solution (the best for the branch). In this case, we simply don't give a hoot since the \
        #   logic will be dominated by the fact that we found a solution.
        if minCost != NS:
            newCost = depth + minCost
            if (newCost < self.bestDepth):
                # print(f"New best depth of {newCost} detected!")
                self.bestDepth = min(self.bestDepth, newCost)

        if minCost == NS and not canProveImpossible:
            # Didn't find a better solution, but skipped over some stuff.
            minCost = SKIP

        # Update cache
        self.cache[amount] = (minCost, depthBudget, depth, minCoinId)

        # print(f"Min-cost for branch {amount} with depth {depth} and budget {depthBudget} is {minCost}")
        return minCost

    # Pearson's test for canonicity from Gemini 3. Applied to all the tails. Only checks canonicity if (last/gcd) = 1.
    # Otherwise, checking canonicity could be prohibitively expensive.
    # TODO: Do more rigorous checking for small n (<1e4 or something) to get more positive results for small-coin tails.
    def build_rev_is_canonical(self, targetAmount, useWeakCanonicity = True):
        coins = self.coins
        n = self.n
        self.isCanonical = [False] * n
        self.isWeaklyCanonical = [False] * n

        normTail = [0]*n
        normTail[-1] = 1

        maxWeakWitness = int(min(2000, sqrt(targetAmount)))

        for i in range(n - 1, -1, -1):
            g = self.revGCD[i]

            # GATE: If normalization doesn't result in a 1-coin,
            # we can't use the simple witness proof.
            if coins[n - 1] // g == 1:
                normTail[i] = coins[i] // g

                # If it ends in 1, we check if Greedy is Optimal for all
                # "Critical" values. For a set with a 1, the critical values
                # are generated by comparing each coin to the ones smaller than it.
                tailIsCanonical = True
                for j in range(i, n - 1):
                    # The 'New' coin in our suffix
                    c_j = normTail[j]
                    # The 'Next' coin
                    c_next = normTail[j + 1]

                    # This is the "Potential Point of Failure" (Witness)
                    # It's the smallest value where the Greedy algorithm is
                    # forced to choose c_j, potentially missing a better
                    # combination of smaller coins.
                    q = (c_j // c_next) + 1
                    w = q * c_next

                    # TEST: Does Greedy(w) using the WHOLE suffix [cID...n-1]
                    # match the Optimal result? Since the set ends in 1,
                    # the 'Optimal' is found by testing the greedy solve
                    # starting from the NEXT coin (j+1).
                    if self.greedy_solve(w, i, normTail) > self.greedy_solve(w, j + 1, normTail):
                        tailIsCanonical = False
                        break

                self.isCanonical[i] = tailIsCanonical
                self.isWeaklyCanonical[i] = tailIsCanonical

            else:
                # Irreducible coin set with min>1. Not canonical, but may be weakly canonical. This check is more expensive, so we value-gate.
                # Use 2DDP due to the potentially massive number of re-visited states. BUT! Only do this if it's not too expensive.
                # We eschew normalization for now: The "gcd-impossible" holes for the set should never get touched. Normalizing
                # would corrupt our global cache.

                self.isCanonical[i] = False
                self.isWeaklyCanonical[i] = False # False unless all witnesses are small enough

                if useWeakCanonicity:
                    smallest_coin = self.coins[-1]

                    # g divides the effort. maxWeakWitness is my "max effort" - so I allow more with a larger gcd!
                    # Strictly control the effort for small targetAmount. Don't complicate the super simple!
                    adjMaxWeakWitness = min(targetAmount//10, maxWeakWitness * g)
                    for amount in range(0, adjMaxWeakWitness, smallest_coin):
                        self.globalCache[amount, smallest_coin] = amount // smallest_coin

                    # 1. Generate Witnesses
                    # Witness w = smallest multiple of c_j > c_i
                    witnesses = set()
                    def getWitnesses():
                        for ii in range(i, n - 1):
                            for jj in range(ii + 1, n):
                                c_i = coins[ii]
                                c_j = coins[jj]
                                w = ((c_i // c_j) + 1) * c_j
                                if w > adjMaxWeakWitness:
                                    return False
                                witnesses.add(w)
                        return True

                    if not getWitnesses():
                        continue
                    self.isWeaklyCanonical[i] = True # True unless some witness protests.

                    # 2. Test Witnesses
                    for w in witnesses:
                        g_count = self.greedy_solve(w, i)
                        if g_count != NS:
                            o_count = self.coinChange2DDP(w, i)  # DP is fast for small w
                            if g_count > o_count:
                                self.isWeaklyCanonical[i] = False  # Feasible but suboptimal detected!

    def greedy_solve(self, amount, start_idx, normTail = None):
        # Only runs when a solution is guaranteed: normTail ends in 1, or
        # amount % gcd(normTail) = 0
        if normTail is None:
            normTail = self.coins

        count = 0
        rem = amount
        for j in range(start_idx, self.n):
            c_norm = normTail[j]
            count += rem // c_norm
            rem %= c_norm
        return count if rem==0 else NS

    def coinChange2DDP(self, amount, minCoinID):
        # INTERNAL helper. Assume revGCD has already been built, along with the relevant portion of self.isCanonical.

        if (amount, minCoinID) in self.globalCache:
            return self.globalCache[amount, minCoinID]

        coin = self.coins[minCoinID]
        gcd = self.revGCD[minCoinID]
        isWeaklyCanonical = self.isWeaklyCanonical[minCoinID]

        if amount % coin == 0:
            # NICE CASE: One and done!
            solution = amount // coin
            self.globalCache[amount, minCoinID] = solution
            return solution
        elif minCoinID == self.n-1:
            # BASE CASE! The last coin doesn't work. Return infeasible.
            self.globalCache[amount, minCoinID] = NS
            return NS

        if amount % gcd != 0:
            # IMPOSSIBLE CASE: Amount is infeasible for this and all future tails! Break
            self.globalCache[amount, minCoinID] = NS
            return NS

        if(isWeaklyCanonical):
            # MAYBE NICE CASE: Solve the greedy problem! If strongly canonical: greedy is feasible. Else, it's optimal if feasible.
            # Either way, it's optimal if feasible, and we ignore it otherwise.
            solution = self.greedy_solve(amount, minCoinID)
            if solution != NS:
                # Best possible with any subset of the tail we have! Set and break.
                self.globalCache[amount, minCoinID] = solution
                return solution

        # NOT NICE CASE! Branch
        bestSolution = NS

        # Pick the coin - if you can!
        if coin < amount: # The coin might be useful - so pick it! Coin != amount for sure! So we use <.
            bestSolution = min(bestSolution, 1+self.coinChange2DDP(amount - coin, minCoinID))

        # Or: Don't pick it!
        bestSolution = min(bestSolution, self.coinChange2DDP(amount, minCoinID+1))

        self.globalCache[amount, minCoinID] = bestSolution
        return bestSolution

    def makeRemainderBasedStableBounds(self, targetAmount):
        # Precondition: n>=3 on entering
        maxCacheSizePerTail = min(targetAmount/10, 1e5)
        maxTotalCache = 10 * maxCacheSizePerTail # don't go overboard if it's degenerate with a bunch of similar coins in a row or something
        self.remainderBasedStableBounds = {} # {minCoinID: ({remainder : (cumVal, cumDepth)}), isComplete}
        coins = self.coins
        n = self.n

        # Trivial cases: tail length is 1 or 2! Skip those guys.
        # (Tail 2 is trivial: Divide amount and both coins by gcd(coins), to get coins p0 and p1, amount a. Solution k. Then:
        # If p1=1 we just have k = amount//p0+amount%p0.
        # Else: Let ra = a % p1, rp = p0 % p1, k = ra * pow(rp, -1, p1) % p1. (The pow computes inverse of rp mod p1.)
        #   Then the optimal solution is k+(a-k*p0)/p1. Closed-form solution either way (given mod-inverse oracle).
        totalSize = 0
        for i in range(n - 3, -1, -1):
            # Decision: "Frontier is part of searched! But not vice-versa."
            searched = {0: (0, 0)}
            frontier = {0: (0, 0)}
            c0 = coins[i]

            # Each frontier: generate remainders from coin tail.
            tail = coins[i+1:]
            searchSize = 1
            isComplete = True

            currDepth = 0
            while(frontier):
                if searchSize >= maxCacheSizePerTail or totalSize + searchSize >= maxTotalCache:
                    isComplete = False
                    break

                currDepth += 1
                newFrontier = {}
                for (rem, (cumVal, cumDepth)) in frontier.items():
                    for coin in tail:
                        newRem = (rem + coin)%c0
                        newCumVal = cumVal + coin
                        # Smaller penalty is better! Fewer total coins needed including c0
                        # We "subsidize" a cost by in essence "the number of copies of c0 we save by using it"
                        newCost = currDepth - newCumVal//c0

                        oldCost = NS
                        newFrontierCost = NS
                        if newRem in searched:
                            # Determine if it's an improvement based on depth + amount // c0
                            (oldCumVal, oldCumDepth) = searched[newRem]
                            oldCost = oldCumDepth - oldCumVal//c0
                        if newRem in newFrontier:
                            (newFrontierCumVal, _) = newFrontier[newRem]
                            newFrontierCost = currDepth - newFrontierCumVal//c0

                        unExplored = newRem not in newFrontier and newRem not in searched
                        strictImproved = newCost<min(oldCost, newFrontierCost)

                        if unExplored or strictImproved:
                            newFrontier[newRem] = (newCumVal, currDepth)

                searched.update(newFrontier)
                frontier = newFrontier
                searchSize = len(searched)

            totalSize += searchSize

            self.remainderBasedStableBounds[i] = (searched, isComplete)
            if not isComplete:
                # We didn't finish this one, and thus will likely not finish any others. Break and save nothing.
                # cID and all smaller cID will populate self.remainderBasedStableBounds with {} on access and give no info.
                break

    def solve2Coin(self, a):
        # PREREQ: self.n>=2 duh. Gosh. You ruined my tots.
        g = self.revGCD[-2]
        if a % g: return NS
        a //= g

        p0 = self.coins[-2]//g
        p1 = self.coins[-1]//g
        if p1 == 1:
            return a//p0 + a%p0
        else:
            # Simply solve a - k*p1 = 0 (mod p0). Rearranging gives k = 1 p1^-1 (mod p0).
            k = (a * pow(p1, -1, p0)) % p0

            if k*p1>a: # Infeasible! Had to use more than amount to reach correct modulus.
                return NS

            return k + (a-k*p1)//p0





#amnt = 1854789
#cns = [4, 8, 32, 96, 202, 1008, 4359, 30985, 1500000]
#amnt = 1854789
#cns = [4, 8, 30, 202, 1008, 4359, 30985, 1500000]
#amnt = 96854789
#cns = [4, 8, 30, 202, 1008, 4359, 30985, 1500000]
#amnt = 10298435
#cns = [5, 9, 105, 20325]
#amnt = 5298435
#cns = [5, 9, 105, 20325]
#amnt = 1529876
#cns = [5, 9, 50, 105, 206, 409, 803, 2302, 6508, 13092, 20325]
#amnt = 1529876
#cns = [5, 10, 50, 105, 206, 409, 803, 2302, 6508, 13092, 20325]
#amnt = 1298345
#cns = [5, 9, 50, 105, 206, 409, 803, 2302, 6508, 13092, 20325]
#amnt = 1298345
#cns = [5, 10, 50, 105, 205, 405, 805, 2305, 6505, 13095, 20325]
#amnt = 9529876
#cns = [1, 5, 10, 25, 50, 100, 200, 500, 1000, 2000, 10000]
#amnt = 9529876
#cns = [1, 5, 10, 25, 50, 100, 200, 500, 1000, 1001, 2000, 10000]
#amnt = 10029876
#cns = [1, 5, 10, 25, 50, 100, 200, 500, 1000, 1001, 2000, 10000]
#amnt = 1529876
#cns = [1, 5, 10, 25, 50, 100, 200, 500, 1000, 1001, 2000, 10000]
#amnt = 100002
#cns = [501, 500, 2]
amnt = 50000051
cns = [int(1e6)+2, 1000, 999, 998, 997, 996, 995]
#amnt = 5000051
#cns = [1000, 999, 998, 997, 996, 995]
#amnt = 1529876
#cns = [1, 5, 10, 25, 50, 100, 200, 500, 1000, 1003, 2000, 2101, 10000, 11201]
#amnt = 1529876
#cns = [2, 3, 10, 25, 50, 100, 200, 500, 1000, 1500, 2000, 2101, 10000, 11201]
#amnt = 1529876
#cns = [2, 3, 10, 25, 50, 100, 200, 500, 1000, 2000, 2101, 10000, 11201]
#amnt = 9529876
#cns = [1, 10000]
#amnt = 166291876
#cns = [101, 10000]
#amnt = 121354250
#cns = [503, 509, 10000]
#amnt = 145945
#cns = [436,83,210,75,286]
#amnt = 979423
#cns = [77,82,84,80,398,286,40,136,162]
#amnt = 6989
#cns = [27,40,244,168,383]
#amnt = 123456
#cns = [77,82,84,80,398,286,40,136,162]
#amnt = 5000001
#cns = [10001, 10000, 5001, 5000]
#amnt = 9999
#cns = [1, 1000, 1110, 4003]
#amnt = 627
#cns = [9,183,255,407,102,174,230]


#print(sys.getrecursionlimit())
sys.setrecursionlimit(100000)
#print(sys.getrecursionlimit())

sln = Solution()


print(f"Coins: {cns}, amount: {amnt}")


t0 = time.time()
#print("\nSolving with DP")
#sln.coinChangeDP(cns, amnt)

t1 = time.time()
#print("\nSolving with coinChangeBranch")
#sln.coinChangeBranch(cns, amnt)

t2 = time.time()
print("\nSolving with coinChangeBranchWithOrderedSearch with BFSStabilityBounds only")
sln.coinChangeBranchWithOrderedSearch(cns, amnt, useCanonicity = False, useBFSStabilityBounds = True)

t3 = time.time()
#print("\nSolving with coinChangeBranchWithOrderedSearch with canonicity")
#sln.coinChangeBranchWithOrderedSearch(cns, amnt, useCanonicity = True, useWeakCanonicity = False)

t4 = time.time()
#print("\nSolving with coinChangeBranchWithOrderedSearch with canonicity and weak canonicity")
#sln.coinChangeBranchWithOrderedSearch(cns, amnt, useCanonicity = True, useWeakCanonicity = True)

t5 = time.time()
print("\nSolving with coinChangeBranchWithOrderedSearch with canonicity, weak canonicity, and Sylvester's bounds")
sln.coinChangeBranchWithOrderedSearch(cns, amnt, useCanonicity = True, useWeakCanonicity = False, useSylvesterStabilityBounds = True)

t6 = time.time()
print("\nSolving with coinChangeBranchWithOrderedSearch with canonicity, weak canonicity, Sylvester's stability bounds, and BFS stability bounds.")
sln.coinChangeBranchWithOrderedSearch(cns, amnt, useCanonicity = True, useWeakCanonicity = False, useSylvesterStabilityBounds = True, useBFSStabilityBounds = True)

t7 = time.time()
print(f"\nDP time: {t1 - t0}, branchTime: {t2 - t1}, orderedBranchWithBFSStabOnly: {t3 - t2}, orderedBranchWithCanonOnly: {t4 - t3}, addWeakCanon: {t5 - t4}, addSylvesterStability: {t6 - t5}, addBFSStability: {t7 - t6}")