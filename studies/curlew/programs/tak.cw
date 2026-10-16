-- Takeuchi's function, as in the Gabriel benchmarks: nested calls with
-- three Int arguments. Then TAKL, the same on lists, where "less than"
-- compares list lengths by walking them.

tak :: Int -> Int -> Int -> Int
tak x y z = if not (y < x) then z else tak (tak (x - 1) y z) (tak (y - 1) z x) (tak (z - 1) x y)

listn :: Int -> [Int]
listn 0 = []
listn n = n : listn (n - 1)

shorter :: [a] -> [a] -> Bool
shorter _ [] = False
shorter [] _ = True
shorter (_:xs) (_:ys) = shorter xs ys

mas :: [Int] -> [Int] -> [Int] -> [Int]
mas x y z = if not (shorter y x) then z
            else mas (mas (tail x) y z) (mas (tail y) z x) (mas (tail z) x y)

main input = "tak 18 12 6 = " ++ show (tak 18 12 6) ++ "\n"
  ++ "takl 12 8 4 = " ++ show (mas (listn 12) (listn 8) (listn 4)) ++ "\n"
