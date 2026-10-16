-- Primes, lazily: the naive sieve on an infinite list (a growing chain
-- of filters), and trial division against the primes found so far.

sieve :: [Int] -> [Int]
sieve (p:xs) = p : sieve [x | x <- xs, x `mod` p /= 0]

primes1 :: [Int]
primes1 = sieve [2 ..]

primes2 :: [Int]
primes2 = 2 : filter isPrime [3, 5 ..]
  where isPrime n = all (\p -> n `mod` p /= 0) (takeWhile (\p -> p * p <= n) primes2)

main input = unlines
  [ "sieve: " ++ show (take 15 primes1) ++ " ... the 300th is " ++ show (primes1 !! 299)
  , "trial division: the 2000th is " ++ show (primes2 !! 1999)
  , "sum of those below 10000: " ++ show (sum (takeWhile (< 10000) primes2))
  ]
