-- Binary trees, after the Benchmarks Game: many complete trees built and
-- checked, and one long-lived tree. Mostly allocation and collection.

data Tree = Nil | Node Tree Tree

make :: Int -> Tree
make 0 = Node Nil Nil
make d = Node (make (d - 1)) (make (d - 1))

check :: Tree -> Int
check Nil = 0
check (Node l r) = 1 + check l + check r

main input = unlines (stretch : map round [4, 6 .. maxD] ++ [longLived])
  where
    maxD = 10
    stretch = "stretch tree of depth " ++ show (maxD + 1) ++ "\t check: " ++ show (check (make (maxD + 1)))
    long = make maxD
    round d = let n = 2 ^ (maxD - d + 4)
                  sumChecks = sum [check (make d) | _ <- [1 .. n]]
              in show n ++ "\t trees of depth " ++ show d ++ "\t check: " ++ show sumChecks
    longLived = "long lived tree of depth " ++ show maxD ++ "\t check: " ++ show (check long)
