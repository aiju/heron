-- Sorting pseudo-random Ints three ways: quicksort by list
-- comprehensions, the prelude's merge sort (sortBy, through Ord), and
-- insertion sort; then checks they agree.

randoms :: Int -> Int -> [Int]
randoms n seed = take n (tail (iterate next seed))
  where next s = (s * 75 + 74) `mod` 65537

qsort :: [Int] -> [Int]
qsort [] = []
qsort (p:xs) = qsort [x | x <- xs, x < p] ++ [p] ++ qsort [x | x <- xs, x >= p]

isort :: [Int] -> [Int]
isort = foldr insert []

sorted :: [Int] -> Bool
sorted (x:y:rest) = x <= y && sorted (y : rest)
sorted _ = True

main input = unlines
  [ "quicksort: " ++ show (take 10 q) ++ " sorted: " ++ show (sorted q)
  , "merge sort: " ++ show (take 10 m) ++ " agrees: " ++ show (m == q)
  , "insertion sort of 500: " ++ show (take 10 i) ++ " agrees: " ++ show (i == sort (take 500 xs))
  , "the median: " ++ show (q !! 1000)
  ]
  where xs = randoms 2000 42
        q = qsort xs
        m = sort xs
        i = isort (take 500 xs)
