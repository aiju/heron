-- Laziness: infinite lists, a list defined in terms of itself, values
-- never evaluated, sharing, seq, strict fields and bang patterns.

data P = P !Int Int

ones :: [Int]
ones = 1 : ones

nats :: [Int]
nats = 0 : map (+ 1) nats

fibs :: [Int]
fibs = 0 : 1 : zipWith (+) fibs (tail fibs)

cyclic :: [Char]
cyclic = let xs = 'a' : 'b' : 'c' : xs in xs

firstOf :: P -> Int
firstOf (P a _) = a

strictLen :: [a] -> Int
strictLen = go 0 where
  go !n [] = n
  go !n (_:xs) = go (n + 1) xs

expensive :: Int -> Int
expensive n = sum [1 .. n]

shared :: Int
shared = let x = expensive 1000 in x + x + x

lazyPair :: (Int, Int)
lazyPair = (1, error "never evaluated")

main input = unlines
  [ show (take 5 ones, take 5 nats, takeWhile (< 100) fibs)
  , show (fibs !! 40)
  , take 10 cyclic
  , show (fst lazyPair, length [undefined, undefined, error "nor this"])
  , show (firstOf (P 7 undefined))
  , show (const 1 (undefined :: Int), snd (undefined :: Int, 2))
  , show (strictLen [1 .. 50000])
  , show shared
  , show (let (a, b) = (b + 1, 10) in a)
  , show (take 3 [x | x <- [1 ..], x * x > 50])
  , show (seq (1 :: Int) 2, (\(_, y) -> y) (undefined :: Int, 3 :: Int))
  , show (zip "abc" [1 ..], lookup 3 (zip [1 ..] "xyz"))
  , show (head (filter (> 1000) (map (* 3) [1 ..])))
  , show (and (cycle [True, False]), or (map (> 10) [1 ..]))
  ]
