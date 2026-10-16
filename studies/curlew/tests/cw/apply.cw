-- Applying functions: partial and over-saturated applications, closures,
-- composition, sections, a CAF of a function type; and enough allocation
-- to collect a few times.

primes :: [Int]
primes = sieve [2..] where sieve (p:xs) = p : sieve [x | x <- xs, x `mod` p /= 0]

compose :: [a -> a] -> a -> a
compose = foldr (.) id

add3 :: Int -> Int -> Int -> Int
add3 x y z = x + y + z

twice f = f . f

applyAll :: [Int -> Int] -> Int -> [Int]
applyAll fs x = map ($ x) fs

data Tree = Leaf | Node Tree Int Tree

build :: Int -> Int -> Tree
build lo hi | lo > hi = Leaf
            | otherwise = let m = (lo + hi) `div` 2 in Node (build lo (m - 1)) m (build (m + 1) hi)

sumT :: Tree -> Int
sumT Leaf = 0
sumT (Node l x r) = sumT l + x + sumT r

curried :: Int -> Int -> Int
curried a = \b -> a * 10 + b

main input = unlines
  [ show (take 30 primes)
  , show (primes !! 300)
  , show (compose [(+1), (*2), subtract 3] 10)
  , show (map (add3 1 2) [10, 20], map (add3 1) [1, 2] <*> [100])
  , show (twice (twice (*2)) 3, twice tail "abcdef")
  , show (applyAll [(+1), add3 1 1, curried 4, \x -> x * x] 7)
  , show (sum (map (\x -> x * x) [1..1000]))
  , show (length (concatMap show [1..800]))
  , show (foldr (+) 0 [1..2000])
  , show (sumT (build 1 3000))
  , show (let xs = [1..3000] :: [Int] in (sum xs, length xs, maximum xs))
  , show (zipWith3 add3 [1,2,3] [10,20,30] [100,200,300])
  , show (iterate (map (+1)) [1,2,3] !! 200)
  ]
  where fs <*> xs = [f x | f <- fs, x <- xs]
